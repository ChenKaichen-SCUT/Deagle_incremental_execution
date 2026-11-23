/* Diagnostic runs only. Wrap an actual executable in one monotonic child interval. */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static long long now_ns(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts)) exit(125);
    return (long long)ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

int main(int argc, char **argv) {
    const char *name = strrchr(argv[0], '/');
    int inner = strcmp(name ? name + 1 : argv[0], "real-gcc") == 0;
    const char *exe = inner ? "/usr/bin/gcc" : getenv("S9_PROFILE_WRAPPER");
    const char *log = getenv("S9_PROFILE_LOG");
    if (!exe || !log || argc < 2) return 125;
    int probe = strcmp(argv[argc - 1], "-") == 0;
    long long begin = now_ns();
    pid_t child = fork();
    if (child == 0) {
        argv[0] = (char *)exe;
        execv(exe, argv);
        _exit(127);
    }
    if (child < 0) return 125;
    int status;
    while (waitpid(child, &status, 0) < 0) if (errno != EINTR) return 125;
    long long end = now_ns();
    int fd = open(log, O_WRONLY | O_APPEND | O_CREAT, 0600);
    if (fd < 0) return 125;
    int count = dprintf(fd, "%s\t%s\t%lld\t%lld\t%d\n", inner ? "gcc" : "wrapper",
                        probe ? "stdin" : "file", begin, end, status);
    if (close(fd) || count < 0) return 125;
    if (WIFSIGNALED(status)) {
        int signo = WTERMSIG(status);
        signal(signo, SIG_DFL);
        raise(signo);
        return 128 + signo;
    }
    return WEXITSTATUS(status);
}
