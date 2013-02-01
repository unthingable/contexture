import os
from setuptools import setup, find_packages


def find_package_data(package, files=()):
    package_data = {}
    for dirpath, _, filenames in os.walk(package):
        for f in files:
            if f in filenames:
                package_path = dirpath.replace('/', '.')
                package_data.setdefault(package_path, []).append(f)
    return package_data

with open('requirements.txt') as f:
    requirements = map(str.strip, f)

setup(name='loggingcontext',
      description='Magic Automatic Logging Context',
      version=os.environ.get('GIT_BRANCH'),
      author='Alex',
      author_email='alex@eat-up.org',
      packages=find_packages(),
      install_requires=requirements,
      package_data=find_package_data('loggingcontext',
                                     files=('config.conf',)),
      entry_points="""
        [console_scripts]
        lcmon=loggingcontext.monitor:monitor_cmd
    """
)
