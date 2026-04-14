//
// Copyright (c) 2022 ZettaScale Technology
// Copyright (c) 2023 Fictionlab sp. z o.o.
// Copyright (c) 2026 genoh-10base-t1s project
//
// This program and the accompanying materials are made available under the
// terms of the Eclipse Public License 2.0 which is available at
// http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
// which is available at https://www.apache.org/licenses/LICENSE-2.0.
//
// SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
//
// Contributors:
//   ZettaScale Zenoh Team, <zenoh@zettascale.tech>
//   Adapted for Microchip Harmony Berkeley Socket API on SAM E70
//
// NOTE: This file adapts the lwIP-based zenoh-pico FreeRTOS network layer
// to use the Microchip Harmony TCP/IP stack Berkeley Socket API.
//
// Key differences from lwIP:
//   - No fcntl() support: blocking/non-blocking is handled via recv timeout
//   - No select()/poll(): replaced with recv(MSG_PEEK) + vTaskDelay polling
//   - SO_RCVTIMEO, SO_KEEPALIVE, TCP_NODELAY not supported by Harmony Berkeley API
//   - shutdown() not available: use closesocket() directly
//   - Socket handle is SOCKET (int16_t), not int
//   - Error check uses SOCKET_ERROR / INVALID_SOCKET, not < 0
//   - No IP_ADD_MEMBERSHIP: multicast is stubbed out
//   - No netif_find()/netif_is_up()/netif_ip4_addr(): network interface
//     discovery is stubbed
//

#include <stdlib.h>
#include <string.h>
#include <errno.h>

#include "FreeRTOS.h"
#include "task.h"

// Microchip Harmony TCP/IP stack headers
#include "configuration.h"
#include "definitions.h"
#include "tcpip/tcpip.h"
#include "tcpip/berkeley_api.h"

// Harmony Berkeley API may not define MSG_PEEK
#ifndef MSG_PEEK
#define MSG_PEEK 0x02
#endif

#ifndef htons
#define htons(x) ((uint16_t)(((x) << 8) | (((x) >> 8) & 0xFF)))
#endif

#include "zenoh-pico/system/platform.h"
#include "zenoh-pico/transport/transport.h"
#include "zenoh-pico/utils/logging.h"
#include "zenoh-pico/utils/mutex.h"
#include "zenoh-pico/utils/pointers.h"
#include "zenoh-pico/utils/result.h"

// ---------------------------------------------------------------------------
// Harmony Berkeley API compatibility helpers
// ---------------------------------------------------------------------------

// Harmony Berkeley API uses SOCKET (int16_t). We store it in int (_socket).
// These helpers bridge the type mismatch.
#define _ZH_SOCK_INVALID  INVALID_SOCKET
#define _ZH_SOCK_ERROR    SOCKET_ERROR

// Helper: close a Harmony Berkeley socket safely.
// Harmony has no shutdown(); closesocket() is the only teardown primitive.
static inline void _zh_closesocket(int sock) {
    if (sock >= 0) {
        closesocket((SOCKET)sock);
    }
}

// Helper: setsockopt wrapper that silently ignores options unsupported by
// Harmony Berkeley API.  Harmony supports a very limited subset of socket
// options; in particular SO_RCVTIMEO, SO_KEEPALIVE, TCP_NODELAY and SO_LINGER
// are NOT available.  Rather than failing the whole connection setup we log a
// debug message and return success.
static inline int _zh_setsockopt_safe(int sock, int level, int optname,
                                      const void *optval, int optlen) {
    // Harmony Berkeley API supported options (as of H3 v3.x):
    //   SOL_SOCKET: SO_SNDBUF, SO_RCVBUF, SO_BROADCAST, SO_REUSEADDR
    //   IPPROTO_TCP: (none that we use)
    //   IPPROTO_IP: (no IP_ADD_MEMBERSHIP)
    //
    // Silently skip unsupported options so that callers written for BSD
    // sockets do not have to be restructured.
    switch (optname) {
        case SO_SNDBUF:
        case SO_RCVBUF:
#ifdef SO_BROADCAST
        case SO_BROADCAST:
#endif
#ifdef SO_REUSEADDR
        case SO_REUSEADDR:
#endif
            // These are supported -- pass through
            return setsockopt((SOCKET)sock, level, optname, optval, optlen);

        default:
            // Unsupported option -- silently succeed
            _Z_DEBUG("Harmony setsockopt: ignoring unsupported option %d on level %d", optname, level);
            return 0;
    }
}

// ---------------------------------------------------------------------------
// Polling delay used as a replacement for select() / poll().
// Harmony Berkeley API has no select().  We poll with recv(MSG_PEEK) in a
// tight loop with short vTaskDelay sleeps.
// ---------------------------------------------------------------------------
#ifndef Z_HARMONY_POLL_INTERVAL_MS
#define Z_HARMONY_POLL_INTERVAL_MS  10  // ms between polls
#endif

// ---------------------------------------------------------------------------
// TCP feature
// ---------------------------------------------------------------------------
#if Z_FEATURE_LINK_TCP == 1

// Harmony Berkeley API has no fcntl().
// We implement blocking/non-blocking as a no-op; the recv timeout is
// controlled by the Harmony stack internally (the default is blocking).
// For non-blocking behaviour we would need a custom recv-with-timeout wrapper,
// but for zenoh-pico the main path uses blocking I/O with timeouts, so this
// is acceptable.
z_result_t _z_socket_set_blocking(const _z_sys_net_socket_t *sock, bool blocking) {
    _ZP_UNUSED(sock);
    _ZP_UNUSED(blocking);
    // Harmony Berkeley API does not support fcntl / O_NONBLOCK.
    // Blocking is the default and only mode.  Return OK so that
    // callers do not treat this as a fatal error.
    return _Z_RES_OK;
}

z_result_t _z_socket_accept(const _z_sys_net_socket_t *sock_in, _z_sys_net_socket_t *sock_out) {
    struct sockaddr naddr;
    int nlen = sizeof(naddr);
    sock_out->_socket = -1;

    // Harmony accept() signature: SOCKET accept(SOCKET s, struct sockaddr *addr, int *addrlen)
    SOCKET con_socket = accept((SOCKET)sock_in->_socket, &naddr, &nlen);
    if (con_socket == INVALID_SOCKET) {
        _Z_ERROR_RETURN(_Z_ERR_GENERIC);
    }

    // Harmony Berkeley API does not support SO_RCVTIMEO, SO_KEEPALIVE,
    // TCP_NODELAY, or SO_LINGER.  We use the safe wrapper which silently
    // ignores unsupported options.
    z_time_t tv;
    tv.tv_sec = Z_CONFIG_SOCKET_TIMEOUT / (uint32_t)1000;
    tv.tv_usec = (Z_CONFIG_SOCKET_TIMEOUT % (uint32_t)1000) * (uint32_t)1000;
    _zh_setsockopt_safe((int)con_socket, SOL_SOCKET, SO_RCVTIMEO, (char *)&tv, sizeof(tv));

    int flags = 1;
    _zh_setsockopt_safe((int)con_socket, SOL_SOCKET, SO_KEEPALIVE, (void *)&flags, sizeof(flags));
#if Z_FEATURE_TCP_NODELAY == 1
    _zh_setsockopt_safe((int)con_socket, IPPROTO_TCP, TCP_NODELAY, (void *)&flags, sizeof(flags));
#endif

    // SO_LINGER not supported -- skip

    sock_out->_socket = (int)con_socket;
    return _Z_RES_OK;
}

void _z_socket_close(_z_sys_net_socket_t *sock) {
    if (sock->_socket >= 0) {
        TCPIP_TCP_Close((TCP_SOCKET)sock->_socket);
    }
    sock->_socket = -1;
}

// Replacement for lwip_select() / FreeRTOS_select():
// Iterate over all peer sockets and use recv(MSG_PEEK) to check if data is
// available.  If no data is ready on any socket, sleep and retry until the
// total wait time reaches Z_CONFIG_SOCKET_TIMEOUT.
z_result_t _z_socket_wait_event(void *v_peers, _z_mutex_rec_t *mutex) {
    _z_transport_peer_unicast_slist_t **peers = (_z_transport_peer_unicast_slist_t **)v_peers;
    uint32_t elapsed_ms = 0;
    uint32_t timeout_ms = Z_CONFIG_SOCKET_TIMEOUT;

    while (elapsed_ms < timeout_ms) {
        bool any_ready = false;

        _z_mutex_rec_mt_lock(mutex);
        _z_transport_peer_unicast_slist_t *curr = *peers;
        while (curr != NULL) {
            _z_transport_peer_unicast_t *peer = _z_transport_peer_unicast_slist_value(curr);
            // Probe with MSG_PEEK -- does not consume data
            uint8_t probe;
            int rb = recv((SOCKET)peer->_socket._socket, (char *)&probe, 1, MSG_PEEK);
            if (rb > 0) {
                peer->_pending = true;
                any_ready = true;
            }
            curr = _z_transport_peer_unicast_slist_next(curr);
        }
        _z_mutex_rec_mt_unlock(mutex);

        if (any_ready) {
            return _Z_RES_OK;
        }

        vTaskDelay(pdMS_TO_TICKS(Z_HARMONY_POLL_INTERVAL_MS));
        elapsed_ms += Z_HARMONY_POLL_INTERVAL_MS;
    }

    // Timeout: no data arrived on any peer socket
    _Z_ERROR_RETURN(_Z_ERR_GENERIC);
}

/*------------------ TCP sockets ------------------*/

z_result_t _z_create_endpoint_tcp(_z_sys_net_endpoint_t *ep, const char *s_address, const char *s_port) {
    z_result_t ret = _Z_RES_OK;

    // Harmony Berkeley API provides getaddrinfo() via berkeley_api.h.
    // However, Harmony's DNS resolver may not support getaddrinfo on all
    // configurations.  We build a sockaddr_in manually for IPv4.
    struct addrinfo hints;
    (void)memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_INET;       // IPv4 only on SAM E70
    hints.ai_socktype = SOCK_STREAM;
    hints.ai_flags = 0;
    hints.ai_protocol = IPPROTO_TCP;

    SYS_CONSOLE_PRINT("[ZP-NET] TCP endpoint %s:%s\r\n", s_address, s_port);
    // Harmony getaddrinfo() may not set the port correctly.
    // Build sockaddr_in manually as a workaround.
    {
        struct addrinfo *ai = (struct addrinfo *)z_malloc(sizeof(struct addrinfo) + sizeof(struct sockaddr_in));
        if (ai == NULL) return _Z_ERR_GENERIC;
        memset(ai, 0, sizeof(struct addrinfo) + sizeof(struct sockaddr_in));
        struct sockaddr_in *sin = (struct sockaddr_in *)(ai + 1);
        sin->sin_family = AF_INET;
        sin->sin_port = htons((uint16_t)atoi(s_port));
        // Parse IP address manually
        unsigned int a, b, c, d;
        if (sscanf(s_address, "%u.%u.%u.%u", &a, &b, &c, &d) == 4) {
            sin->sin_addr.s_addr = (uint32_t)a | ((uint32_t)b << 8) | ((uint32_t)c << 16) | ((uint32_t)d << 24);
        }
        /* sin->sin_len not present in all implementations */
        ai->ai_family = AF_INET;
        ai->ai_socktype = SOCK_STREAM;
        ai->ai_protocol = IPPROTO_TCP;
        ai->ai_addrlen = sizeof(struct sockaddr_in);
        ai->ai_addr = (struct sockaddr *)sin;
        ai->ai_next = NULL;
        ep->_iptcp = ai;
        SYS_CONSOLE_PRINT("[ZP-NET] manual addr port=%d\r\n", atoi(s_port));
        return _Z_RES_OK;
    }
    if (getaddrinfo(s_address, s_port, &hints, &ep->_iptcp) < 0) {
        _Z_ERROR_LOG(_Z_ERR_GENERIC);
        ret = _Z_ERR_GENERIC;
        return ret;
    }
    ep->_iptcp->ai_addr->sa_family = ep->_iptcp->ai_family;

    return ret;
}

void _z_free_endpoint_tcp(_z_sys_net_endpoint_t *ep) {
    // We allocated with z_malloc, not getaddrinfo, so use z_free
    z_free(ep->_iptcp);
}

z_result_t _z_open_tcp(_z_sys_net_socket_t *sock, const _z_sys_net_endpoint_t rep, uint32_t tout) {
    // Use Harmony NATIVE TCP API instead of Berkeley sockets.
    // Berkeley connect() doesn't send SYN packets properly.
    struct sockaddr_in *sin = (struct sockaddr_in *)rep._iptcp->ai_addr;
    uint16_t port = htons(sin->sin_port);  /* back to host order */
    IP_MULTI_ADDRESS remoteAddr;
    remoteAddr.v4Add.Val = sin->sin_addr.s_addr;

    SYS_CONSOLE_PRINT("[ZP-NET] TCPIP_TCP_ClientOpen port=%d ip=%d.%d.%d.%d\r\n",
        port,
        remoteAddr.v4Add.v[0], remoteAddr.v4Add.v[1],
        remoteAddr.v4Add.v[2], remoteAddr.v4Add.v[3]);

    TCP_SOCKET nativeSkt = TCPIP_TCP_ClientOpen(IP_ADDRESS_TYPE_IPV4, port, &remoteAddr);
    if (nativeSkt == INVALID_SOCKET) {
        SYS_CONSOLE_PRINT("[ZP-NET] ClientOpen FAILED\r\n");
        sock->_socket = -1;
        return _Z_ERR_GENERIC;
    }
    SYS_CONSOLE_PRINT("[ZP-NET] native socket=%d\r\n", (int)nativeSkt);

    // Poll TCPIP_TCP_IsConnected until handshake completes
    uint32_t connect_tout = (tout < 10000) ? 10000 : tout;
    for (uint32_t wait = 0; wait < connect_tout; wait += 50) {
        if (TCPIP_TCP_IsConnected(nativeSkt)) {
            SYS_CONSOLE_PRINT("[ZP-NET] TCP connected after %lums!\r\n", (unsigned long)wait);
            sock->_socket = (int)nativeSkt;
            return _Z_RES_OK;
        }
        vTaskDelay(pdMS_TO_TICKS(50));
    }

    SYS_CONSOLE_PRINT("[ZP-NET] TCP connect TIMEOUT\r\n");
    TCPIP_TCP_Close(nativeSkt);
    sock->_socket = -1;
    return _Z_ERR_GENERIC;
}

z_result_t _z_listen_tcp(_z_sys_net_socket_t *sock, const _z_sys_net_endpoint_t lep) {
    z_result_t ret = _Z_RES_OK;

    SOCKET s = socket(lep._iptcp->ai_family, lep._iptcp->ai_socktype, lep._iptcp->ai_protocol);
    sock->_socket = (int)s;

    if (s == INVALID_SOCKET) {
        sock->_socket = -1;
        _Z_ERROR_RETURN(_Z_ERR_GENERIC);
    }

    // Harmony does not support SO_KEEPALIVE, TCP_NODELAY, SO_LINGER
    int flags = 1;
    _zh_setsockopt_safe(sock->_socket, SOL_SOCKET, SO_KEEPALIVE, (void *)&flags, sizeof(flags));
#if Z_FEATURE_TCP_NODELAY == 1
    _zh_setsockopt_safe(sock->_socket, IPPROTO_TCP, TCP_NODELAY, (void *)&flags, sizeof(flags));
#endif

    struct addrinfo *it = NULL;
    if (ret == _Z_RES_OK) {
        for (it = lep._iptcp; it != NULL; it = it->ai_next) {
            if (bind((SOCKET)sock->_socket, it->ai_addr, it->ai_addrlen) < 0) {
                _Z_ERROR_LOG(_Z_ERR_GENERIC);
                ret = _Z_ERR_GENERIC;
                break;
            }
            if (listen((SOCKET)sock->_socket, Z_LISTEN_MAX_CONNECTION_NB) < 0) {
                _Z_ERROR_LOG(_Z_ERR_GENERIC);
                ret = _Z_ERR_GENERIC;
                break;
            }
        }
    }
    if (ret != _Z_RES_OK) {
        _zh_closesocket(sock->_socket);
        sock->_socket = -1;
    }
    return ret;
}

void _z_close_tcp(_z_sys_net_socket_t *sock) {
    if (sock->_socket >= 0) {
        // Harmony has no shutdown(); closesocket() is the only teardown
        _zh_closesocket(sock->_socket);
        sock->_socket = -1;
    }
}

size_t _z_read_tcp(const _z_sys_net_socket_t sock, uint8_t *ptr, size_t len) {
    // Use Harmony native TCP API for reading
    TCP_SOCKET nativeSkt = (TCP_SOCKET)sock._socket;
    // Wait for data with timeout
    for (int tries = 0; tries < 100; tries++) {  // ~5 sec max
        uint16_t avail = TCPIP_TCP_GetIsReady(nativeSkt);
        if (avail > 0) {
            uint16_t toRead = (avail < (uint16_t)len) ? avail : (uint16_t)len;
            uint16_t rb = TCPIP_TCP_ArrayGet(nativeSkt, ptr, toRead);
            return (size_t)rb;
        }
        if (!TCPIP_TCP_IsConnected(nativeSkt)) {
            return SIZE_MAX;  // Connection lost
        }
        vTaskDelay(pdMS_TO_TICKS(50));
    }
    return SIZE_MAX;  // Timeout
}

size_t _z_read_exact_tcp(const _z_sys_net_socket_t sock, uint8_t *ptr, size_t len) {
    size_t n = 0;
    uint8_t *pos = &ptr[0];

    do {
        size_t rb = _z_read_tcp(sock, pos, len - n);
        if ((rb == SIZE_MAX) || (rb == 0)) {
            n = rb;
            break;
        }

        n = n + rb;
        pos = _z_ptr_u8_offset(pos, rb);
    } while (n != len);

    return n;
}

size_t _z_send_tcp(const _z_sys_net_socket_t sock, const uint8_t *ptr, size_t len) {
    // Use Harmony native TCP API for writing
    TCP_SOCKET nativeSkt = (TCP_SOCKET)sock._socket;
    if (!TCPIP_TCP_IsConnected(nativeSkt)) {
        return SIZE_MAX;
    }
    // Wait until TX buffer has space
    for (int tries = 0; tries < 50; tries++) {
        uint16_t space = TCPIP_TCP_PutIsReady(nativeSkt);
        if (space >= (uint16_t)len) {
            uint16_t sb = TCPIP_TCP_ArrayPut(nativeSkt, ptr, (uint16_t)len);
            TCPIP_TCP_Flush(nativeSkt);
            return (size_t)sb;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    // Partial write if buffer smaller than requested
    uint16_t space = TCPIP_TCP_PutIsReady(nativeSkt);
    if (space > 0) {
        uint16_t sb = TCPIP_TCP_ArrayPut(nativeSkt, ptr, space);
        TCPIP_TCP_Flush(nativeSkt);
        return (size_t)sb;
    }
    return SIZE_MAX;
}

#else  // Z_FEATURE_LINK_TCP != 1

z_result_t _z_socket_set_blocking(const _z_sys_net_socket_t *sock, bool blocking) {
    _ZP_UNUSED(sock);
    _ZP_UNUSED(blocking);
    _Z_ERROR("Function not yet supported on this system");
    _Z_ERROR_RETURN(_Z_ERR_GENERIC);
}

z_result_t _z_socket_accept(const _z_sys_net_socket_t *sock_in, _z_sys_net_socket_t *sock_out) {
    _ZP_UNUSED(sock_in);
    _ZP_UNUSED(sock_out);
    _Z_ERROR("Function not yet supported on this system");
    _Z_ERROR_RETURN(_Z_ERR_GENERIC);
}

void _z_socket_close(_z_sys_net_socket_t *sock) { _ZP_UNUSED(sock); }

z_result_t _z_socket_wait_event(void *peers, _z_mutex_rec_t *mutex) {
    _ZP_UNUSED(peers);
    _ZP_UNUSED(mutex);
    _Z_ERROR("Function not yet supported on this system");
    _Z_ERROR_RETURN(_Z_ERR_GENERIC);
}

#endif  // Z_FEATURE_LINK_TCP == 1

// ---------------------------------------------------------------------------
// UDP feature (shared endpoint creation for unicast and multicast)
// ---------------------------------------------------------------------------
#if Z_FEATURE_LINK_UDP_UNICAST == 1 || Z_FEATURE_LINK_UDP_MULTICAST == 1

z_result_t _z_create_endpoint_udp(_z_sys_net_endpoint_t *ep, const char *s_address, const char *s_port) {
    z_result_t ret = _Z_RES_OK;

    struct addrinfo hints;
    (void)memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_INET;      // IPv4 only on SAM E70
    hints.ai_socktype = SOCK_DGRAM;
    hints.ai_flags = 0;
    hints.ai_protocol = IPPROTO_UDP;

    if (getaddrinfo(s_address, s_port, &hints, &ep->_iptcp) < 0) {
        _Z_ERROR_LOG(_Z_ERR_GENERIC);
        ret = _Z_ERR_GENERIC;
        return ret;
    }
    ep->_iptcp->ai_addr->sa_family = ep->_iptcp->ai_family;

    return ret;
}

void _z_free_endpoint_udp(_z_sys_net_endpoint_t *ep) {
    freeaddrinfo(ep->_iptcp);
}

#endif  // Z_FEATURE_LINK_UDP_UNICAST == 1 || Z_FEATURE_LINK_UDP_MULTICAST == 1

// ---------------------------------------------------------------------------
// UDP unicast
// ---------------------------------------------------------------------------
#if Z_FEATURE_LINK_UDP_UNICAST == 1

z_result_t _z_open_udp_unicast(_z_sys_net_socket_t *sock, const _z_sys_net_endpoint_t rep, uint32_t tout) {
    z_result_t ret = _Z_RES_OK;

    SOCKET s = socket(rep._iptcp->ai_family, rep._iptcp->ai_socktype, rep._iptcp->ai_protocol);
    sock->_socket = (int)s;

    if (s != INVALID_SOCKET) {
        // SO_RCVTIMEO not supported by Harmony -- silently ignore
        z_time_t tv;
        tv.tv_sec = tout / (uint32_t)1000;
        tv.tv_usec = (tout % (uint32_t)1000) * (uint32_t)1000;
        _zh_setsockopt_safe(sock->_socket, SOL_SOCKET, SO_RCVTIMEO, (char *)&tv, sizeof(tv));

        if (ret != _Z_RES_OK) {
            _zh_closesocket(sock->_socket);
            sock->_socket = -1;
        }
    } else {
        _Z_ERROR_LOG(_Z_ERR_GENERIC);
        sock->_socket = -1;
        ret = _Z_ERR_GENERIC;
    }

    return ret;
}

z_result_t _z_listen_udp_unicast(_z_sys_net_socket_t *sock, const _z_sys_net_endpoint_t lep, uint32_t tout) {
    (void)sock;
    (void)lep;
    (void)tout;
    z_result_t ret = _Z_RES_OK;

    // @TODO: To be implemented
    _Z_ERROR_LOG(_Z_ERR_GENERIC);
    ret = _Z_ERR_GENERIC;

    return ret;
}

void _z_close_udp_unicast(_z_sys_net_socket_t *sock) {
    if (sock->_socket >= 0) {
        _zh_closesocket(sock->_socket);
        sock->_socket = -1;
    }
}

size_t _z_read_udp_unicast(const _z_sys_net_socket_t sock, uint8_t *ptr, size_t len) {
    struct sockaddr_in raddr;
    int addrlen = sizeof(struct sockaddr_in);

    int rb = recvfrom((SOCKET)sock._socket, (char *)ptr, len, 0, (struct sockaddr *)&raddr, &addrlen);
    if (rb < 0) {
        return SIZE_MAX;
    }
    return (size_t)rb;
}

size_t _z_read_exact_udp_unicast(const _z_sys_net_socket_t sock, uint8_t *ptr, size_t len) {
    size_t n = 0;
    uint8_t *pos = &ptr[0];

    do {
        size_t rb = _z_read_udp_unicast(sock, pos, len - n);
        if ((rb == SIZE_MAX) || (rb == 0)) {
            n = rb;
            break;
        }

        n = n + rb;
        pos = _z_ptr_u8_offset(pos, (ptrdiff_t)n);
    } while (n != len);

    return n;
}

size_t _z_send_udp_unicast(const _z_sys_net_socket_t sock, const uint8_t *ptr, size_t len,
                           const _z_sys_net_endpoint_t rep) {
    int sb = sendto((SOCKET)sock._socket, (const char *)ptr, len, 0,
                    rep._iptcp->ai_addr, rep._iptcp->ai_addrlen);
    if (sb < 0) {
        return SIZE_MAX;
    }
    return (size_t)sb;
}

#endif  // Z_FEATURE_LINK_UDP_UNICAST == 1

// ---------------------------------------------------------------------------
// UDP multicast
// ---------------------------------------------------------------------------
#if Z_FEATURE_LINK_UDP_MULTICAST == 1

// Harmony Berkeley API does NOT support:
//   - netif_find() / netif_is_up() / netif_ip4_addr()  (lwIP netif API)
//   - IP_ADD_MEMBERSHIP / IP_DROP_MEMBERSHIP
//
// Multicast is therefore not functional with Harmony Berkeley API.
// These functions return errors so that zenoh-pico falls back to unicast.
// A future implementation could use the Harmony NET_PRES or raw TCPIP_MAC
// APIs for multicast group management.

// Stub replacement for lwIP __get_ip_from_iface().
// Returns 0 (failure) because Harmony Berkeley API has no netif enumeration.
static unsigned int __get_ip_from_iface(const char *iface, int sa_family, struct sockaddr **lsockaddr) {
    _ZP_UNUSED(iface);
    _ZP_UNUSED(sa_family);
    _ZP_UNUSED(lsockaddr);

    // Harmony Berkeley API does not expose network interface enumeration.
    // For a single-interface system (typical for SAM E70 + LAN8670), the
    // caller could hardcode the IP, but we leave this as a stub for now.
    _Z_DEBUG("Harmony: netif discovery not available, multicast not supported");
    return 0;
}

z_result_t _z_open_udp_multicast(_z_sys_net_socket_t *sock, const _z_sys_net_endpoint_t rep,
                                 _z_sys_net_endpoint_t *lep, uint32_t tout, const char *iface) {
    _ZP_UNUSED(sock);
    _ZP_UNUSED(rep);
    _ZP_UNUSED(lep);
    _ZP_UNUSED(tout);
    _ZP_UNUSED(iface);

    // Harmony Berkeley API does not support IP_ADD_MEMBERSHIP.
    // Multicast open is not available.  Use TCP unicast instead.
    _Z_ERROR("UDP multicast not supported on Harmony Berkeley API");
    sock->_socket = -1;
    _Z_ERROR_RETURN(_Z_ERR_GENERIC);
}

z_result_t _z_listen_udp_multicast(_z_sys_net_socket_t *sock, const _z_sys_net_endpoint_t rep,
                                   uint32_t tout, const char *iface, const char *join) {
    _ZP_UNUSED(sock);
    _ZP_UNUSED(rep);
    _ZP_UNUSED(tout);
    _ZP_UNUSED(iface);
    _ZP_UNUSED(join);

    // Harmony Berkeley API does not support IP_ADD_MEMBERSHIP.
    // Multicast listen is not available.  Use TCP unicast instead.
    _Z_ERROR("UDP multicast not supported on Harmony Berkeley API");
    sock->_socket = -1;
    _Z_ERROR_RETURN(_Z_ERR_GENERIC);
}

void _z_close_udp_multicast(_z_sys_net_socket_t *sockrecv, _z_sys_net_socket_t *socksend,
                            const _z_sys_net_endpoint_t rep, const _z_sys_net_endpoint_t lep) {
    _ZP_UNUSED(rep);
    _ZP_UNUSED(lep);

    // No IP_DROP_MEMBERSHIP to call -- just close sockets
    if (sockrecv->_socket >= 0) {
        _zh_closesocket(sockrecv->_socket);
        sockrecv->_socket = -1;
    }
    if (socksend->_socket >= 0) {
        _zh_closesocket(socksend->_socket);
        socksend->_socket = -1;
    }
}

size_t _z_read_udp_multicast(const _z_sys_net_socket_t sock, uint8_t *ptr, size_t len,
                             const _z_sys_net_endpoint_t lep, _z_slice_t *addr) {
    _ZP_UNUSED(lep);
    _ZP_UNUSED(addr);

    // This should never be called since _z_open_udp_multicast and
    // _z_listen_udp_multicast always fail, but provide a safe stub.
    struct sockaddr_in raddr;
    int replen = sizeof(struct sockaddr_in);

    int rb = recvfrom((SOCKET)sock._socket, (char *)ptr, len, 0,
                      (struct sockaddr *)&raddr, &replen);
    if (rb < 0) {
        return SIZE_MAX;
    }
    return (size_t)rb;
}

size_t _z_read_exact_udp_multicast(const _z_sys_net_socket_t sock, uint8_t *ptr, size_t len,
                                   const _z_sys_net_endpoint_t lep, _z_slice_t *addr) {
    size_t n = 0;
    uint8_t *pos = &ptr[0];

    do {
        size_t rb = _z_read_udp_multicast(sock, pos, len - n, lep, addr);
        if ((rb == SIZE_MAX) || (rb == 0)) {
            n = rb;
            break;
        }

        n = n + rb;
        pos = _z_ptr_u8_offset(pos, (ptrdiff_t)n);
    } while (n != len);

    return n;
}

size_t _z_send_udp_multicast(const _z_sys_net_socket_t sock, const uint8_t *ptr, size_t len,
                             const _z_sys_net_endpoint_t rep) {
    int sb = sendto((SOCKET)sock._socket, (const char *)ptr, len, 0,
                    rep._iptcp->ai_addr, rep._iptcp->ai_addrlen);
    if (sb < 0) {
        return SIZE_MAX;
    }
    return (size_t)sb;
}

#endif  // Z_FEATURE_LINK_UDP_MULTICAST == 1

// ---------------------------------------------------------------------------
// Unsupported transports
// ---------------------------------------------------------------------------
#if Z_FEATURE_LINK_BLUETOOTH == 1
#error "Bluetooth not supported yet on FreeRTOS + Harmony port of Zenoh-Pico"
#endif

#if Z_FEATURE_LINK_SERIAL == 1
#error "Serial not supported yet on FreeRTOS + Harmony port of Zenoh-Pico"
#endif

#if Z_FEATURE_RAWETH_TRANSPORT == 1
#error "Raw ethernet transport not supported yet on FreeRTOS + Harmony port of Zenoh-Pico"
#endif
