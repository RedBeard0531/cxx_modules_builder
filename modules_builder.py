#!/usr/bin/env python3

import ninja_syntax
import yaml
from pprint import pprint
import os
import sys
import io
import shutil
import subprocess

try:
    from yaml import CSafeLoader as LOADER
except ImportError:
    print("falling back to python yaml parser, consider installing pyyaml C extension")
    from yaml import SafeLoader as LOADER

MAKE_NINJA = os.path.realpath(__file__)
HEADER = os.path.join(os.path.dirname(MAKE_NINJA), 'header.ninja')

def get_clang():
    clang = shutil.which('clang++')
    version = subprocess.check_output([clang, '--version'])
    if ('RELEASE' in str(version)):
        print("You have a release version of clang++ on your PATH, "
              "but this requires a patched git build of clang and ninja.")
        print("Please see the README.")
        sys.exit(1)
    return clang

def parse_makefile(path):
    # TODO less crappy parser
    with open(path) as f:
        text = f.read()
    text = text.replace('\\\n', '')
    target, source = text.split(':', 1)
    return (
        target.strip(),
        [s.strip() for s in source.split()],
    )

def flatten(in_list, prefix=''):
    assert(isinstance(in_list, list))
    out_list = []
    for item in in_list:
        if isinstance(item, dict):
            for path, sub_list in item.items():
                combined = os.path.join(prefix, path)
                out_list.extend(flatten(sub_list, combined))
        else:
            out_list.append(os.path.join(prefix, item))
    return out_list

def parse_flags_file(path):
    deps = []
    mod_name = None
    with open(path) as f:
        for line in f:
            if not line: continue
            line = line.strip()
            dep_prefix = '-fmodule-file='
            mod_prefix = '-fmodule-name='
            if line.startswith(mod_prefix):
                assert not mod_name
                mod_name = line[len(mod_prefix):]
            elif line.startswith(dep_prefix):
                suffix = '.pcm'
                assert(line.endswith(suffix))
                deps.append(line[len(dep_prefix):-len(suffix)])
            elif line.startswith('-x '):
                pass
            else:
                assert not line.startswith('-')
    return mod_name, deps

with open('build.yml') as f:
    config = yaml.load(f, Loader=LOADER)

header_units = flatten(config['header_units'])
libs = config['libs']
bins = config['bins']

build_dir = config.get('build_root', 'build')
mod_link_dir = os.path.join(build_dir, 'mod_links/')

def to_out_base(path):
    return os.path.join(build_dir, path.replace(os.sep, '_'))

def to_mod_link(mod):
    return os.path.join(mod_link_dir, mod.replace(':', '=')) + '.pcm'

def write_if_changed(s, path, *, force=False):
    if not force and os.path.exists(path):
        with open(path) as f:
            if f.read() == s:
                return

    with open(path, 'w') as f:
        f.write(s)

def make_ninja():
    os.makedirs(mod_link_dir, exist_ok=True)
    sources = []
    for lib in libs:
        libs[lib]['sources'] = flatten(libs[lib]['sources'])
        sources += libs[lib]['sources']

    for bin in bins:
        bins[bin]['sources'] = flatten(bins[bin]['sources'])
        sources += bins[bin]['sources']

    ninja = ninja_syntax.Writer(io.StringIO())
    ninja.comment('This was created by cxx_modules_builder. DO NOT EDIT.')
    ninja.variable('MAKE_NINJA', MAKE_NINJA)
    ninja.variable('CXX', get_clang())
    ninja.newline()
    ninja.comment('START HEADER')
    with open(HEADER) as header:
        ninja.output.write(header.read())
    ninja.comment('END HEADER')
    ninja.newline()

    objs = []
    maybe_mod_scans = []
    scans = []
    pcms = []
    for hu in header_units:
        out_base = to_out_base(hu)

        obj = out_base + '.o'
        pcm = out_base + '.pcm'
        pcm_dyndeps = pcm + '.dd'
        pcm_flags = pcm + '.flags'

        scans.append(pcm_dyndeps)
        pcms.append(pcm)
        objs.append(obj)

        ninja.build(
            pcm_dyndeps, 'SCAN',
            hu,
            implicit=['$CXX', '$MAKE_NINJA', 'make_ninja.yml'],
            #implicit_outputs=pcm_flags,
            variables=dict(
                KIND='c++-header',
                PCM_FILE=pcm,
                PCMFLAGS_FILE=pcm_flags,
            ))
        ninja.build(
            pcm, 'HEADER_UNIT',
            hu,
            order_only=[pcm_dyndeps, 'maybe_mod_scans'],
            implicit='$CXX',
            #implicit=pcm_flags,
            variables=dict(
                dyndep=pcm_dyndeps,
                PCMFLAGS_FILE=pcm_flags,
            ))
        ninja.build(obj, 'HEADER_UNIT_CXX', pcm, implicit='$CXX')
        ninja.newline()

    for cpp in sources:
        out_base = to_out_base(cpp)
        pcm = out_base + '.pcm'
        obj = out_base + '.o'
        obj_flags = obj + '.flags'
        obj_dyndeps = obj + '.dd'

        maybe_mod_scans.append(obj_dyndeps)
        scans.append(obj_dyndeps)
        objs.append(obj)

        ninja.build(
            obj_dyndeps, 'MAYBE_MODULE_SCAN',
            cpp,
            implicit=['$CXX', '$MAKE_NINJA', 'make_ninja.yml'],
            #implicit_outputs=pcm_flags,
            variables=dict(
                KIND='c++-module',
                PCM_FILE=obj,
                PCMFLAGS_FILE=obj_flags,
            ))

        if cpp in config['module_exclusions']:
            #HACK! disabling the -fmodule-file flags now also removes the input source
            #      so we sneak it back in as an extra param here...
            obj_flags = '/dev/null ' + cpp

        for rule, target in [('CXX', obj), ('CXXPRE', pcm)]:
            ninja.build(
                target, rule,
                cpp,
                implicit='$CXX',
                order_only=[obj_dyndeps, 'maybe_mod_scans'],
                variables=dict(
                    dyndep=obj_dyndeps,
                    FLAGS_FILE=obj_flags,
                ))

    for bin in bins:
        out = to_out_base(bin)
        deps_file = out + '.dd'

        libdeps = bins[bin]['libdeps']
        sources = set(bins[bin]['sources'])
        syslibdeps = set(bins.get('syslibdeps', []))

        def add_libdep_sources(libdeps):
            for libdep in libdeps:
                for s in libs[libdep]['sources']:
                    sources.add(s)
                for l in libs[libdep].get('syslibdeps', ()):
                    syslibdeps.add(l)
                add_libdep_sources(libs[libdep]['libdeps'])
        add_libdep_sources(libdeps)

        ninja.build(
            deps_file, 'LINKSCAN',
            [to_out_base(s)+'.o.dd' for s in sorted(sources)],
            implicit='$MAKE_NINJA',
        )

        variables = {}
        if syslibdeps:
            variables['EXTRALIBS'] = ['-l' + l for l in sorted(syslibdeps)]

        ninja.build(out, 'BIN', deps_file,
                    #implicit=deps_file+'.flags',
                    variables=variables)

    ninja.newline()
    ninja.build('maybe_mod_scans', 'phony', maybe_mod_scans)
    ninja.build('scans', 'phony', scans)
    ninja.build('pcms', 'phony', pcms)
    ninja.build('objs', 'phony', objs)
    ninja.build('bins', 'phony', [to_out_base(b) for b in bins])
    ninja.default('bins')

    ninja.newline()
    ninja.build('build.ninja', 'GENERATOR', implicit=[MAKE_NINJA, HEADER, 'build.yml'])

    with open('build.ninja', 'w') as f:
        f.write(ninja.output.getvalue())

def scan_header_unit(raw, header_name, dyndeps, pcmflags):
    #TODO this will eventually need to handle named module imports from headers,
    #     but since clang currently chokes on those I'm omitting it as a simplification.
    _, sources = parse_makefile(raw)
    source_mods = []
    source_reals = set()
    hu_reals = {}

    # This is an O(N + M) algorithm for checking os.samefile() on
    # every file in sources against every file in header_units
    def file_id(path):
        stat = os.stat(path)
        return (stat.st_dev, stat.st_ino)

    self_id = file_id(header_name)
    for s in sources:
        s_id = file_id(s)
        if s_id != self_id: # the input header is listed as a source
            source_reals.add(s_id)

    for hu in header_units:
        hu_reals[file_id(hu)] = to_out_base(hu) + '.pcm'

    for s in source_reals:
        if s in hu_reals:
            source_mods.append(hu_reals[s])

    pcm = to_out_base(header_name) + '.pcm'

    ninja = ninja_syntax.Writer(io.StringIO())
    ninja.variable('ninja_dyndep_version', 1)
    ninja.build(pcm, 'dyndep', implicit=source_mods)

    # XXX because the flags file isn't in the ninja deps graph, restat isn't quite safe :(
    write_if_changed(ninja.output.getvalue(), dyndeps)

    write_if_changed(
        ''.join(f'-fmodule-file={s}\n' for s in source_mods),
        pcmflags)

def link_scan(deps_file, *inputs):
    objs = set()
    considered = set(inputs)
    queue = list(inputs)
    while queue:
        input = queue.pop()
        assert(input.endswith('.dd'))
        obj = input[:-3]
        objs.add(obj)
        _, deps = parse_flags_file(obj + '.flags')
        for dep in deps:
            if dep.startswith(mod_link_dir): continue # no transitive link to imported named modules.
            objs.add(dep + '.o')
            continue

            # This shouldn't be needed. Leaving it so it can easily be enabled to check if it fixes issues.
            dyndep = dep + '.dd'
            if (dyndep not in considered):
                print('opening:', obj + '.flags')
                considered.add(dyndep)
                queue.append(dyndep)


    objs = sorted(objs)

    ninja = ninja_syntax.Writer(io.StringIO())
    ninja.variable('ninja_dyndep_version', 1)
    ninja.build(deps_file[:-len('.dd')], 'dyndep', implicit=objs)
    write_if_changed(ninja.output.getvalue(), deps_file, force=True)

    write_if_changed(
        '\n'.join(objs),
        deps_file + '.flags',
        force=True)

def maybe_module_scan(raw_deps, import_module_file, cpp_file_name, dyndeps, cxxflags):
    #TODO see how much code can be shared with header_unit_scan
    _, sources = parse_makefile(raw_deps)
    source_mods = []
    source_reals = set()
    hu_reals = {}

    with open(import_module_file) as f: import_module_file = f.readlines()
    #if import_module_file: print(''.join(import_module_file))

    imports = []
    is_module = import_module_file and import_module_file[-1].startswith('module,')
    if is_module:
        _, is_export, mod_name = import_module_file.pop().split(',', 2)
        mod_name = mod_name.strip()
        is_export = bool(is_export) or ':' in mod_name
        if not is_export:
            # Pure module implementation units should be treated as plain cpps
            is_module = False
            imports.append(mod_name) # implicit import of primary interface
        for line in import_module_file:
            line = line.strip()
            if line.startswith(':'):
                line = mod_name + line
            imports.append(line)
    else:
        for line in import_module_file:
            imports.append(line.strip())


    # This is an O(N + M) algorithm for checking os.samefile() on
    # ever file in sources against every file in header_units
    def file_id(path):
        stat = os.stat(path)
        return (stat.st_dev, stat.st_ino)

    self_id = file_id(cpp_file_name)
    for s in sources:
        s_id = file_id(s)
        if s_id != self_id: # the input header is listed as a source
            source_reals.add(s_id)

    for hu in header_units:
        hu_reals[file_id(hu)] = to_out_base(hu) + '.pcm'

    for s in source_reals:
        if s in hu_reals:
            source_mods.append(hu_reals[s])

    for i in imports:
        source_mods.append(to_mod_link(i))

    source_mods.sort()
    module_flags = [f'-fmodule-file={s}' for s in source_mods]

    obj = to_out_base(cpp_file_name) + '.o'
    pcm = to_out_base(cpp_file_name) + '.pcm'

    ninja = ninja_syntax.Writer(io.StringIO())
    ninja.variable('ninja_dyndep_version', 1)

    if is_module: # May have become false if pure impl unit
        ninja.build(pcm, 'dyndep', implicit=source_mods, implicit_outputs=to_mod_link(mod_name))
        write_if_changed('\n'.join(module_flags + [f'-fmodule-name={mod_name}'])  + '\n-o ' + to_mod_link(mod_name), pcm + '.flags')
        write_if_changed(to_mod_link(mod_name), cxxflags)
    else:
        # Need to be here, but no effect
        ninja.build(pcm, 'dyndep')
        # no need to write pcmflags since pcm won't be built
        write_if_changed('\n'.join(module_flags + ['-x c++', cpp_file_name]), cxxflags)

    ninja.build(obj, 'dyndep', implicit=([pcm] if is_module else source_mods))
    write_if_changed(ninja.output.getvalue(), dyndeps)

if __name__ == '__main__':
    if len(sys.argv) == 1:
        sys.exit(make_ninja())

    sub_commands = {
        '--scan': scan_header_unit,
        '--link-scan': link_scan,
        '--maybe-module-scan': maybe_module_scan,
    }

    if sys.argv[1] not in sub_commands:
        print('Unknown mode: ', sys.argv[1])
        sys.exit(1)

    sys.exit(sub_commands[sys.argv[1]](*sys.argv[2:]))
