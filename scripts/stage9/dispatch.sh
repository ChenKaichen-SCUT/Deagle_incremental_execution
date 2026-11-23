#!/bin/sh
# The frontend controller owns this private directory and waits for this process.
set -u
root=$INCDEAGLE_FRONT_SPOOL
slot="$root/c.$$"
umask 077
mkdir "$slot" || exit 125
printf '%s\0' "$@" > "$slot/argv" || exit 125
pwd -P > "$slot/cwd" || exit 125
kind=unknown
if { [ "$#" -eq 4 ] && [ "$1" = -E ] && [ "$2" = - ] && [ "$3" = -o ] && [ "$4" = - ]; } ||
   { [ "$#" -eq 6 ] && [ "$1" = -E ] && [ "$2" = -x ] && [ "$3" = c++ ] && [ "$4" = - ] && [ "$5" = -o ] && [ "$6" = - ]; }; then
    kind=probe
else
    previous=''
    safe=yes
    for arg do
        case "$previous" in ''|-E|-m32|-m64|-std=*|-D?*|-U?*|-I?*) ;; *) safe=no ;; esac
        previous=$arg
    done
    if [ "$safe" = yes ] && [ "$#" -gt 1 ] && [ "$1" = -E ] && [ -f "$previous" ]; then kind=file; fi
fi
printf '%s\n' "$kind" > "$slot/kind" || exit 125
if [ "$kind" = unknown ]; then
    exec /usr/bin/python3 "$INCDEAGLE_FRONT_MODULE/../stage3/record_gcc.py" "$@"
fi
if [ "$kind" = probe ]; then
    cat > "$slot/stdin" || exit 125
    /usr/bin/gcc "$@" < "$slot/stdin" > "$slot/stdout"
else
    /usr/bin/gcc -MD -MF "$slot/deps" -MT incdeagle "$@" > "$slot/stdout"
fi
rc=$?
printf '%s\n' "$rc" > "$slot/status" || exit 125
if [ "$kind" = file ]; then
    mkfifo -m 600 "$slot/ack" || exit 125
    exec 3<>"$slot/ack" || exit 125
    printf '%s\n' "$$" > "$root/requests" || exit 125
    IFS= read -r ack <&3 || exit 125
    exec 3>&-
fi
cat "$slot/stdout" || exit 125
exit "$rc"
