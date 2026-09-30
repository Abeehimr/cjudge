#!/bin/sh
set -eu

# Mount only this container's private cgroup namespace, never the host tree.
test "$(cat /proc/self/cgroup)" = '0::/'
mkdir -p /run/cjudge-cgroup /run/isolate/locks /var/local/lib/isolate
mount -t cgroup2 none /run/cjudge-cgroup
mkdir /run/cjudge-cgroup/manager
echo $$ > /run/cjudge-cgroup/manager/cgroup.procs
echo '+cpu +memory +pids' > /run/cjudge-cgroup/cgroup.subtree_control

# Expose only these devices to inner sandboxes, not the container's /dev.
mkdir -p /run/cjudge-dev
mknod -m 666 /run/cjudge-dev/null c 1 3
mknod -m 666 /run/cjudge-dev/zero c 1 5
mknod -m 666 /run/cjudge-dev/urandom c 1 9
isolate --check-config
exec "$@"
