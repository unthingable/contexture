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


setup(name='loggingcontext',
      description='Logging Magic',
      version=0.1,
      author='Alex',
      author_email='alkouznetsov@ebay.com',
      packages=find_packages(),
      # package_data=find_package_data('loggingcontext',
      #                                files=('proxies.txt',)),
      install_requires=[
        # 'tproxy',
        'stomp.py',
        'pyyaml',
        'nose',
      ]
)
