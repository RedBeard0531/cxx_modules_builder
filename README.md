# CXX Modules Builder
Compiles projects using C++20 modules and header units.

Only supports master branches of clang and ninja, with [patches](patches/)

This is still very much a POC. It may eat your homework.

## Examples

You can find an example configuration for
[cxx-modules-sandbox](https://github.com/mathstuf/cxx-modules-sandbox) in
[examples/cxx-modules-sandbox.build.yaml](examples/cxx-modules-sandbox.build.yml).
To try it:

```bash
# Apply patches and compile clang and ninja
export PATH="path/to/patched/clang/bin:path/to/patched/ninja/bin:$PATH"
git clone https://github.com/RedBeard0531/cxx_modules_builder
git clone https://github.com/mathstuf/cxx-modules-sandbox

pip3 install --user -r cxx_modules_builder/requirements.txt # or install pyyaml some other way
cd cxx-modules-sandbox
cp ../cxx_modules_builder/examples/cxx-modules-sandbox.build.yml ./build.yml
../cxx_modules_builder/modules_builder.py
ninja
```

## Configuration

`modules_builder.py` currently takes no arguments and is completely configured
by a `build.yml` file in the working directory, which should generally be the
root of your project. A basic `build.yaml` contains the following:

```yaml
# Where to store build output.
build_root: build

# List header units.
header_units:
  - path/to/header.h
  # As an optional convenience, you can use nesting to avoid duplicating
  # directories in all file lists.
  - src:
    - include:
      - header1.h
      - header2.h
      - details:
        - secrets.h
  # Absolute paths are also accepted.
  - /usr/include/c++/v1:
    - algorithm
    - string
    - vector

# Libraries (currently just treated as a named collection of files,
# so no .a or .so will be built)
- libs:
  reader: # Name of lib
    libdeps: [] # Other libs this depends on 
    sources: # List of source files
      - src/reader.cpp
  worker:
    libdeps:
      - reader
    syslibdeps: # Optional. Passed with -lNAME when linking
      - m
      - rt
    sources:
      - src/worker:
        - worker.cpp
        - utils.cpp

# Binaries
- bins:
  frobnicator:
    libdeps:
      # transitive libdeps and syslibdeps are pulled in automatically
      - worker
    syslibdeps:
      - z
    sources:
      - src/frobnicator.cpp
```

## TODOs
* Features
  + [ ] Support basic settings on command line (compiler, build_root, etc)
  + [ ] Support configuring the compiler flags without editing `header.ninja`
  + [ ] Support choosing names other than `build.ninja` to keep multiple configs around
  + [ ] Allow including `build.yml` files in subdirectories
  + [ ] Globs in file lists
* Implementation
  + [ ] Use separate `rule`s for compiling from `.cpp` -> `.o` vs `.pcm` -> `.o`
  + [ ] Use a better scanner
  + [ ] Look into gcc support
* Documentation
  + [ ] More examples
* External
  + [ ] File issue with ninja so we won't need patch anymore (need minimal repro first)
  + [ ] [ninja can't handle multiple outputs and `deps = gcc`](https://github.com/ninja-build/ninja/pull/1534)
  + [ ] Keep an eye on clang bugs to remove patches and workarounds
    * [ ] [deduction guides + header units = :cry:](https://bugs.llvm.org/show_bug.cgi?id=42639) 
    * [ ] [`import` + `clang -E` = :skull:](https://bugs.llvm.org/show_bug.cgi?id=42472)
