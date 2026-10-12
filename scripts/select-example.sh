#!/bin/sh
set -eu

targets=$1
shift

if ! command -v fzf >/dev/null 2>&1; then
  printf '%s\n' 'fzf is required for interactive selection. Install it with brew install fzf, or pass EXAMPLE=01 through EXAMPLE=09.' >&2
  exit 2
fi
if [ ! -t 0 ]; then
  printf '%s\n' 'Example selection needs a terminal. For scripts, pass EXAMPLE=01 through EXAMPLE=09.' >&2
  exit 2
fi

selected=$(printf '%s\n' "$@" | fzf --prompt='Example> ' --header="make $targets" --height=40% --reverse --no-multi) || {
  printf '%s\n' 'No example selected; nothing ran.' >&2
  exit 130
}

# Accept only one of the offered directory names before invoking Make again.
for example in "$@"; do
  if [ "$selected" = "$example" ]; then
    printf '%s\n' "$selected"
    exit 0
  fi
done
printf '%s\n' 'Invalid example selection; nothing ran.' >&2
exit 2
