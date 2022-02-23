import distutils.ccompiler
import distutils.sysconfig
import glob
import os
import platform
import shutil
import tempfile

from setuptools import setup, find_packages, Extension

def get_ijson_version():
    """Get version from code without fully importing it"""
    _globals = {}
    with open(os.path.join('ijson', 'version.py')) as f:
        code = f.read()
    exec(code, _globals)
    return _globals['__version__']

setupArgs = dict(
    name = 'ijson',
    version = get_ijson_version(),
    author = 'Rodrigo Tobar, Ivan Sagalaev',
    author_email = 'rtobar@icrar.org, maniac@softwaremaniacs.org',
    url = 'https://github.com/ICRAR/ijson',
    license = 'BSD',
    description = 'Iterative JSON parser with standard Python iterator interfaces',
    long_description = open('README.rst').read(),
    long_description_content_type = 'text/x-rst',

    classifiers = [
        'Development Status :: 5 - Production/Stable',
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: Implementation :: CPython',
        'Programming Language :: Python :: Implementation :: PyPy',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
    packages = find_packages(exclude=['test']),
)

# Check if the yajl library + headers are present
# We don't use compiler.has_function because it leaves a lot of files behind
# without properly cleaning up
def yajl_present():

    compiler = distutils.ccompiler.new_compiler(verbose=1)
    distutils.sysconfig.customize_compiler(compiler) # CC, CFLAGS, LDFLAGS, etc

    fname = tempfile.mktemp(".c", "yajl_version")
    try:
        with open(fname, "wt") as f:
            f.write('''
            #include <yajl/yajl_version.h>
            int main(int args, char **argv)
            {
            #if YAJL_MAJOR != 2
                fail to compile
            #else
                yajl_version();
            #endif
                return 0;
            }
            ''')

        try:
            objs = compiler.compile([fname])
            compiler.link_shared_lib(objs, 'a', libraries=["yajl"])
            return True
        finally:
            os.remove(compiler.library_filename('a', lib_type='shared'))
            for obj in objs:
                os.remove(obj)

    except:
        return False
    finally:
        if os.path.exists(fname):
            os.remove(fname)


def patch_yajl_sources():
    """Make yajl sources ready for direct compilation against them"""
    # cp cextern/yajl -R $yajl_sources_copy
    # mkdir $yajl_sources_copy/yajl
    # cp $yajl_sources_copy/src/api/*.h $yajl_sources_copy/yajl
    patched_sources = os.path.join(tempfile.mkdtemp(), 'yajl')
    shutil.copytree(os.path.join('cextern', 'yajl'), patched_sources)
    headers_original = os.path.join(patched_sources, 'src', 'api')
    headers_copy = os.path.join(patched_sources, 'yajl')
    shutil.copytree(headers_original, headers_copy)
    return patched_sources


extra_sources = []
extra_include_dirs = []
libs = ['yajl']
embed_yajl = os.environ.get('IJSON_EMBED_YAJL', None) == '1'
if not embed_yajl:
    have_yajl = yajl_present()
else:
    yajl_sources = patch_yajl_sources()
    extra_sources = sorted(glob.glob(os.path.join(yajl_sources, 'src', '*.c')))
    extra_sources.remove(os.path.join(yajl_sources, 'src', 'yajl_version.c'))
    extra_include_dirs = [yajl_sources, os.path.join(yajl_sources, 'src')]
    libs = []
if embed_yajl or have_yajl:
    yajl_ext = Extension('ijson.backends._yajl2',
                         language='c',
                         sources=sorted(glob.glob('ijson/backends/yajl2_c/*.c')) + extra_sources,
                         include_dirs=['ijson/backends/yajl2_c'] + extra_include_dirs,
                         libraries=libs,
                         depends=glob.glob('ijson/backends/yajl2_c/*.h'))
    setupArgs['ext_modules'] = [yajl_ext]

setup(**setupArgs)
