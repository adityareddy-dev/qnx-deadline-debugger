#define _POSIX_C_SOURCE 200809L
#ifdef __QNXNTO__
#define _QNX_SOURCE 1
#endif

#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#ifdef __QNXNTO__
#include <sys/neutrino.h>
#include <sys/trace.h>
#endif

#define NS_PER_SECOND UINT64_C(1000000000)
#define MS UINT64_C(1000000)
#define JOBS 20
#define PERIOD_NS (100 * MS)
#define DEADLINE_NS (20 * MS)

struct worker {
    const char *name;
    int priority;
    uint64_t offset_ns;
    uint64_t work_ns;
};

static uint64_t epoch_ns;

static void fail(const char *operation, int error)
{
    fprintf(stderr, "%s: %s\n", operation, strerror(error));
    exit(EXIT_FAILURE);
}

static void check(int error, const char *operation)
{
    if (error != 0)
        fail(operation, error);
}

static uint64_t now_ns(clockid_t clock)
{
    struct timespec value;
    if (clock_gettime(clock, &value) == -1)
        fail("clock_gettime", errno);
    return (uint64_t)value.tv_sec * NS_PER_SECOND + (uint64_t)value.tv_nsec;
}

static void sleep_until(uint64_t time_ns)
{
    struct timespec target = {
        .tv_sec = (time_t)(time_ns / NS_PER_SECOND),
        .tv_nsec = (long)(time_ns % NS_PER_SECOND)
    };
    int error;
    do {
        error = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &target, NULL);
    } while (error == EINTR);
    check(error, "clock_nanosleep");
}

static void mark(const char *text)
{
#ifdef __QNXNTO__
    if (TraceEvent(_NTO_TRACE_INSERTUSRSTREVENT, 100, text) == -1)
        fail("TraceEvent", errno);
#else
    (void)text;
    fprintf(stderr, "Recording requires QNX 8.0 and an instrumented kernel.\n");
    exit(EXIT_FAILURE);
#endif
}

static void burn_cpu(uint64_t budget_ns)
{
    uint64_t start = now_ns(CLOCK_THREAD_CPUTIME_ID);
    while (now_ns(CLOCK_THREAD_CPUTIME_ID) - start < budget_ns) {
    }
}

static void *run_worker(void *argument)
{
    const struct worker *worker = argument;
    char text[384];
    int policy;
    struct sched_param actual;

#ifdef __QNXNTO__
    check(pthread_setname_np(pthread_self(), worker->name), "pthread_setname_np");
#endif
    check(pthread_getschedparam(pthread_self(), &policy, &actual),
          "pthread_getschedparam");
    if (policy != SCHED_FIFO || actual.sched_priority != worker->priority)
        fail("unexpected scheduling policy or priority", EINVAL);

    snprintf(text, sizeof(text),
             "DD1 worker=%s pid=%ld tid=%lu priority=%d offset_ns=%" PRIu64
             " work_ns=%" PRIu64,
             worker->name, (long)getpid(), (unsigned long)pthread_self(),
             worker->priority, worker->offset_ns, worker->work_ns);
    mark(text);

    for (unsigned job = 0; job < JOBS; ++job) {
        uint64_t release = epoch_ns + job * PERIOD_NS + worker->offset_ns;
        uint64_t deadline = release + DEADLINE_NS;
        uint64_t start, finish;

        sleep_until(release);
        start = now_ns(CLOCK_MONOTONIC);
        snprintf(text, sizeof(text),
                 "DD1 start worker=%s job=%u release_ns=%" PRIu64
                 " deadline_ns=%" PRIu64 " now_ns=%" PRIu64,
                 worker->name, job, release, deadline, start);
        mark(text);
        burn_cpu(worker->work_ns);
        finish = now_ns(CLOCK_MONOTONIC);
        snprintf(text, sizeof(text),
                 "DD1 finish worker=%s job=%u now_ns=%" PRIu64
                 " deadline_ns=%" PRIu64,
                 worker->name, job, finish, deadline);
        mark(text);
    }
    return NULL;
}

static void create_worker(pthread_t *thread, struct worker *worker)
{
    pthread_attr_t attributes;
    struct sched_param parameters = { .sched_priority = worker->priority };

    check(pthread_attr_init(&attributes), "pthread_attr_init");
    check(pthread_attr_setinheritsched(&attributes, PTHREAD_EXPLICIT_SCHED),
          "pthread_attr_setinheritsched");
    check(pthread_attr_setschedpolicy(&attributes, SCHED_FIFO),
          "pthread_attr_setschedpolicy");
    check(pthread_attr_setschedparam(&attributes, &parameters),
          "pthread_attr_setschedparam");
    check(pthread_create(thread, &attributes, run_worker, worker), "pthread_create");
    check(pthread_attr_destroy(&attributes), "pthread_attr_destroy");
}

int main(int argc, char **argv)
{
    struct worker control = { "control", 20, 5 * MS, 2 * MS };
    struct worker background = { "background", 30, 0, 30 * MS };
    pthread_t control_thread, background_thread;
    char text[384];

    if (argc != 2 || (strcmp(argv[1], "fault") && strcmp(argv[1], "fixed"))) {
        fprintf(stderr, "usage: %s fault|fixed\n", argv[0]);
        return EXIT_FAILURE;
    }
    if (sysconf(_SC_NPROCESSORS_ONLN) != 1) {
        fprintf(stderr, "Run this workload in a guest with exactly one CPU.\n");
        return EXIT_FAILURE;
    }
#ifdef __QNXNTO__
    if (TraceEvent(_NTO_TRACE_QUERYSUPPORT) != _NTO_TRACE_SUPPINSTR) {
        fprintf(stderr, "An instrumented QNX kernel is required.\n");
        return EXIT_FAILURE;
    }
#endif
    if (!strcmp(argv[1], "fixed"))
        background.priority = 10;

    epoch_ns = now_ns(CLOCK_MONOTONIC) + NS_PER_SECOND;
    snprintf(text, sizeof(text),
             "DD1 config mode=%s pid=%ld epoch_ns=%" PRIu64
             " period_ns=%" PRIu64 " deadline_ns=%" PRIu64 " jobs=%d cpus=1",
             argv[1], (long)getpid(), epoch_ns, PERIOD_NS, DEADLINE_NS, JOBS);
    mark(text);
    create_worker(&background_thread, &background);
    create_worker(&control_thread, &control);
    check(pthread_join(control_thread, NULL), "pthread_join control");
    check(pthread_join(background_thread, NULL), "pthread_join background");
    mark("DD1 complete");
    puts("Workload complete. Read the kernel capture for timing results.");
    return EXIT_SUCCESS;
}
