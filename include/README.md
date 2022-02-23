The libraries in this include directory were generated using git subtree:

- git subtree add --prefix include/TM1py https://github.com/cubewise-code/tm1py.git 1.9.0 --squash
- git subtree add --prefix include/urllib3 https://github.com/urllib3/urllib3.git 1.26.8 --squash
- git subtree add --prefix include/wcwidth https://github.com/jquast/wcwidth.git 0.2.5 --squash
- git subtree add --prefix include/prettytable https://github.com/jazzband/prettytable.git 3.1.1 --squash
- git subtree add --prefix include/mdxpy https://github.com/cubewise-code/mdxpy.git 0.3 --squash
- git subtree add --prefix include/requests https://github.com/psf/requests.git v2.27.1 --squash
- git subtree add --prefix include/charset_normalizer https://github.com/Ousret/charset_normalizer.git  2.0.12 --squash
- git subtree add --prefix include/idna https://github.com/kjd/idna.git v3.3 --squash
- git subtree add --prefix include/ijson https://github.com/ICRAR/ijson.git v3.1.4 --squash
- git subtree add --prefix include/pytz https://github.com/stub42/pytz.git release_2021.3 --squash
- git subtree add --prefix include/pyyaml https://github.com/yaml/pyyaml.git 6.0 --squash

This is necessary at the moment because package control does not support dependent packages with the python 3.8 plugin
host