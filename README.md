# websocket-server

WebSocket/HTTP server/client library for Python.

## Description

This is a small stand-alone library for WebSocket servers/clients and generic
HTTP servers. It extends Python's HTTP server framework, providing -- aside
from WebSocket functionality -- convenient use of cookies, query string
parameters, POSTed HTML forms, request routing, and richer HTTP logs than
the standard library provides. WebSocket client functionality is provided as
well.

## Installation

Use the usual methods, like cloning the repository and running `setup.py install`, or
`pip install git+https://github.com/CylonicRaider/websocket-server.git`.

## Example

After having installed the library (or having it available locally otherwise), run

    python -m websocket_server.examples

in a command line, and navigate your WebSocket-enabled Web browser to
[http://localhost:8080/](http://localhost:8080/).

## Documentation

Apply the *pydoc* tool of your choice to the package.
