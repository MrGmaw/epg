#!/usr/bin/env bash
# Restaura archivos base sin cambios desde el historial del mismo repositorio.
# Permite usar este bloque como reemplazo total en un repositorio Git existente,
# incluso si al subirlo se eliminaron accidentalmente archivos base no modificados.
set -euo pipefail

FILES=(
  requirements.txt
  scripts/build_epg.py
  scripts/build_latam_epg.py
  scripts/mitv_utc.py
  scripts/mitv_logos.py
  scripts/apply_local_logos.py
  scripts/tvc_resilient.py
  scripts/validate_outputs.py
)

restore_one() {
  local path="$1"
  if [[ -s "$path" ]]; then
    echo "Base presente: $path"
    return 0
  fi

  local commit="" candidate
  while IFS= read -r candidate; do
    [[ -n "$candidate" ]] || continue
    if git cat-file -e "${candidate}:${path}" 2>/dev/null; then
      commit="$candidate"
      break
    fi
  done < <(git rev-list --all -- "$path")

  if [[ -z "$commit" ]]; then
    echo "ERROR: no se encontró una versión utilizable de $path en el historial Git." >&2
    return 1
  fi

  mkdir -p "$(dirname "$path")"
  git show "${commit}:${path}" > "$path"
  test -s "$path"
  echo "Base restaurada: $path desde ${commit:0:12}"
}

for path in "${FILES[@]}"; do
  restore_one "$path"
done
