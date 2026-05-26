import http.server, os
os.chdir('/Users/suhail/Downloads/ghgrp_real')
http.server.test(HandlerClass=http.server.SimpleHTTPRequestHandler, port=8734, bind='127.0.0.1')
