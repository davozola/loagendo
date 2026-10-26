#!/bin/bash
# Descarga los feeds candidatos del censo a tmp/feeds/ para revisarlos (26-10-2026). Uso: bash scripts/probar_feeds.sh
UA="Ontoca/1.4 (+https://ontoca.com)"
mkdir -p tmp/feeds && cd tmp/feeds || exit 1
get() { curl -s -L -m 60 -A "$UA" -o "$1" -w "%{http_code}  %{size_download} B  $1\n" "$2"; }
get zumzeig.ics      "https://calendar.google.com/calendar/ical/c_np5nor07t98ts9orcgdlbo7vhc%40group.calendar.google.com/public/basic.ics"
get mercat_feed.xml  "https://mercatflors.cat/es/feed/"
get mercat_wpjson.json "https://mercatflors.cat/wp-json/"
get mercat_robots.txt "https://mercatflors.cat/robots.txt"
get bikini_feed.xml  "https://bikinibcn.com/feed/"
get bikini_wpjson.json "https://bikinibcn.com/wp-json/"
get bikini_robots.txt "https://bikinibcn.com/robots.txt"
get bikini_conciertos.html "https://bikinibcn.com/conciertos/"
get zumzeig_robots.txt "https://zumzeigcine.coop/robots.txt"
