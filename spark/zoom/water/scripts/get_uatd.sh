#!/usr/bin/env bash
# UATD per-file download via the figshare API (the article-level zip URL returned 0 bytes).
cd ~/forge/zoom/water
log(){ echo "[$(date +%H:%M:%S)] $*"; }
get(){ curl -fL --retry 5 -C - -o "$1" "$2" && log "$1 ok $(stat -c %s $1)" && (mkdir -p uatd && cd uatd && unzip -oq "../$1" && log "$1 unzipped") || log "$1 FAILED"; }
get UATD_Test_1.zip https://ndownloader.figshare.com/files/37857276 &
get UATD_Test_2.zip https://ndownloader.figshare.com/files/37857279 &
get UATD_Training.zip https://ndownloader.figshare.com/files/37883163 &
wait; log "UATD done"; find uatd -name '*.xml' | wc -l
