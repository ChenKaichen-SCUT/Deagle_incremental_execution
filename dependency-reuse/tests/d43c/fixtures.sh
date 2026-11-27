#!/usr/bin/env bash
set -euo pipefail
src=$(realpath "$1")
tree=$(realpath "$2")
micro=$(realpath "$3")
out=$(realpath -m "$4")
mkdir -p "$out/bin" "$out/fixtures"
f=(-O2 -std=c++11 -DDEAGLE_D43C_AUDIT -DD43C_FIXTURE -I"$tree/src" -I"$tree/minisat-2.2.1")
lib="$tree/src/solvers/solvers.a"
g++ "${f[@]}" -DRECORD_PROOFS -DD41_TRIPLETS "$src/tests/d3/native.cpp" "$lib" -o "$out/bin/fixture"
g++ "${f[@]}" "$src/tests/d43b/native.cpp" "$lib" -o "$out/bin/opaque"
g++ "${f[@]}" "$src/tests/d41/lifetime.cpp" "$lib" -o "$out/bin/lifetime"
for case in deferred-RF deferred-guard immediate-RF immediate-guard unit-guard block direct root-chain minimize-gc domain Q U; do
  base="$micro/triplets/$case"
  if [ ! -f "$base/spec" ]; then base="$micro/d4/$case"; fi
  dest="$out/fixtures/$case"
  mkdir "$dest"
  cp "$base/spec" "$dest/spec"
  (cd "$dest"; "$out/bin/fixture" spec proof.bin >stdout 2>stderr)
  if [ -f "$base/same/decl" ]; then cp "$base/same/decl" "$dest/decl"
  else cp "$(find "$base" -type f -name decl -print -quit)" "$dest/decl"; fi
done
d="$out/fixtures/dynamic-CO";mkdir "$d";"$out/bin/opaque" unknown "$d" > "$d/stdout"
cat > "$d/decl" <<'EOF'
N 0 0 0 0 1
N 1 1 0 0 1
D 0 -1 -1 -1 M
D 4 0 -1 -1 M
D 4 1 -1 -1 M
EOF
d="$out/fixtures/same-slot";mkdir "$d";cp "$out/fixtures/root-chain/"{decl,spec} "$d/"
(cd "$d"; D43C_SAME_GROUP=1 "$out/bin/fixture" spec proof.bin >stdout 2>stderr)
d="$out/fixtures/rollback";mkdir "$d";cp "$out/fixtures/deferred-RF/decl" "$d/decl"
(cd "$d"; "$out/bin/lifetime" >stdout 2>stderr; cp lifetime.bin proof.bin)
d="$out/fixtures/missing-source";mkdir "$d"
cat > "$d/spec" <<'EOF'
4
po x#1 x#2 0
rf x#1 x#2 1
guard x#1 0
guard x#2 0
A 1
EOF
cat > "$d/decl" <<'EOF'
N 0 0 0 0 1
N 1 1 0 1 1
D 0 -1 -1 -1 M
D 1 0 1 -1 M
D 3 0 1 2 M
D 4 0 -1 -1 M
D 4 1 -1 -1 M
D 5 0 -1 -1 M
D 5 1 -1 -1 M
D 6 0 1 -1 M
D 7 0 -1 -1 M
D 7 1 -1 -1 M
EOF
(cd "$d"; "$out/bin/fixture" spec proof.bin >stdout 2>stderr)

d="$out/fixtures/empty-PO-APO";mkdir "$d"
cat > "$d/spec" <<'EOF'
4
apo x#1 x#2 0
po x#2 x#1 0
A
EOF
cat > "$d/decl" <<'EOF'
N 0 1 0 0 0
N 1 1 0 0 0
O 0 1
I 1 0
D 0 -1 -1 -1 M
D 1 1 0 -1 M
D 2 0 1 -1 M
EOF
(cd "$d"; "$out/bin/fixture" spec proof.bin >stdout 2>stderr)

d="$out/fixtures/branch-edges";mkdir "$d"
g++ "${f[@]}" "$src/tests/d3/native_scope.cpp" "$lib" -o "$out/bin/scope"
(cd "$d"; "$out/bin/scope" scope.bin dynamic.bin alias.bin >stdout 2>stderr)

d="$out/fixtures/shorten-empty";mkdir "$d"
cat > "$d/spec" <<'EOF'
2
B 1
B -1 2
B -2
A
EOF
printf 'D 0 -1 -1 -1 M\n' > "$d/decl"
(cd "$d"; "$out/bin/fixture" spec proof.bin >stdout 2>stderr)

d="$out/fixtures/shared-theory";mkdir "$d";cp "$out/fixtures/block/"{decl,spec} "$d/"
(cd "$d"; D43C_SAME_GROUP=1 "$out/bin/fixture" spec proof.bin >stdout 2>stderr)
