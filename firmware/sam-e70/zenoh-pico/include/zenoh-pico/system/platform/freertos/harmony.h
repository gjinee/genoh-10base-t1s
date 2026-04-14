//
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
// Platform types for FreeRTOS + Microchip Harmony TCP/IP Berkeley Socket API.
//
// Harmony Berkeley API uses standard BSD socket types (struct sockaddr,
// struct addrinfo, int socket handles) so the type layout is the same as
// the lwIP variant.  The difference is in which headers provide the types.
//

#ifndef ZENOH_PICO_SYSTEM_FREERTOS_HARMONY_TYPES_H
#define ZENOH_PICO_SYSTEM_FREERTOS_HARMONY_TYPES_H

#include <time.h>

#include "FreeRTOS.h"
#include "semphr.h"

// Harmony TCP/IP stack headers providing Berkeley socket types
#include "configuration.h"
#include "tcpip/tcpip.h"
#include "tcpip/berkeley_api.h"

#ifdef __cplusplus
extern "C" {
#endif

#if Z_FEATURE_MULTI_THREAD == 1
#include "event_groups.h"

typedef struct {
    const char *name;
    UBaseType_t priority;
    size_t stack_depth;
#if (configSUPPORT_STATIC_ALLOCATION == 1)
    bool static_allocation;
    StackType_t *stack_buffer;
    StaticTask_t *task_buffer;
#endif /* SUPPORT_STATIC_ALLOCATION */
} z_task_attr_t;

typedef struct {
    TaskHandle_t handle;
    EventGroupHandle_t join_event;
    void *(*fun)(void *);
    void *arg;
#if (configSUPPORT_STATIC_ALLOCATION == 1)
    StaticEventGroup_t join_event_buffer;
#endif /* SUPPORT_STATIC_ALLOCATION */
} _z_task_t;

typedef struct {
    SemaphoreHandle_t handle;
#if (configSUPPORT_STATIC_ALLOCATION == 1)
    StaticSemaphore_t buffer;
#endif /* SUPPORT_STATIC_ALLOCATION */
} _z_mutex_t;

typedef _z_mutex_t _z_mutex_rec_t;

typedef struct {
    SemaphoreHandle_t mutex;
    SemaphoreHandle_t sem;
    int waiters;
#if (configSUPPORT_STATIC_ALLOCATION == 1)
    StaticSemaphore_t mutex_buffer;
    StaticSemaphore_t sem_buffer;
#endif /* SUPPORT_STATIC_ALLOCATION */
} _z_condvar_t;

typedef TaskHandle_t _z_task_id_t;
#endif  // Z_MULTI_THREAD == 1

typedef TickType_t z_clock_t;
typedef struct timeval z_time_t;

// Harmony Berkeley API socket handle is SOCKET (typedef int16_t).
// We store it in an int for compatibility with the zenoh-pico codebase
// which uses int throughout.  The network.c layer casts to SOCKET where
// needed when calling Harmony Berkeley API functions.
typedef struct {
    union {
#if Z_FEATURE_LINK_TCP == 1 || Z_FEATURE_LINK_UDP_MULTICAST == 1 || Z_FEATURE_LINK_UDP_UNICAST == 1
        int _socket;
#endif
    };
} _z_sys_net_socket_t;

// Harmony Berkeley API provides struct addrinfo via berkeley_api.h,
// compatible with the standard BSD definition.
typedef struct {
    union {
#if Z_FEATURE_LINK_TCP == 1 || Z_FEATURE_LINK_UDP_MULTICAST == 1 || Z_FEATURE_LINK_UDP_UNICAST == 1
        struct addrinfo *_iptcp;
#endif
    };
} _z_sys_net_endpoint_t;

#ifdef __cplusplus
}
#endif

#endif  // ZENOH_PICO_SYSTEM_FREERTOS_HARMONY_TYPES_H
