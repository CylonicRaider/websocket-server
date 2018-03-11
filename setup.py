#!/usr/bin/env python

from distutils.core import setup

setup(name='websocket_server',
      version='2.0',
      description='Stand-alone WebSocket/HTTP server/client library',
      author='@CylonicRaider',
      url='https://github.com/CylonicRaider/websocket-server',
      packages=['websocket_server'],
      package_data={'websocket_server': ['testpage.html']})
