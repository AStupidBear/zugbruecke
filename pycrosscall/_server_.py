#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""

PYCROSSCALL
Calling routines in Windows DLLs from Python scripts running on unixlike systems
https://github.com/s-m-e/pycrosscall

	pycrosscall/_server_.py: Started with Python on Wine, executing DLL calls

	Required to run on platform / side: [WINE]

	Copyright (C) 2017 Sebastian M. Ernst <ernst@pleiszenburg.de>

<LICENSE_BLOCK>
The contents of this file are subject to the GNU Lesser General Public License
Version 2.1 ("LGPL" or "License"). You may not use this file except in
compliance with the License. You may obtain a copy of the License at
https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt
https://github.com/s-m-e/pycrosscall/blob/master/LICENSE

Software distributed under the License is distributed on an "AS IS" basis,
WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License for the
specific language governing rights and limitations under the License.
</LICENSE_BLOCK>

"""


# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# IMPORT
# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

import argparse
import ctypes
import os
from pprint import pformat as pf
import sys
import traceback

from log import log_class
from rpc import (
	mp_server_class
	)


# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# WINE SERVER CLASS
# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

class wine_server_class:


	def __init__(self, session_id, parameter):

		# Store session id and parameter
		self.id = session_id
		self.p = parameter

		# Start logging session and connect it with log on unix side
		self.log = log_class(self.id, self.p)

		# Status log
		self.log.out('[_server_] STARTING ...')

		# Mark session as up
		self.up = True

		# Start dict for dll files and routines
		self.dll_dict = {}

		# Create server
		self.server = rpc_server_alternative(
			('localhost', self.p['port_server_ctypes']),
			requestHandler = rpc_requesthandler
			)
		self.server.set_log(self.log)
		self.server.set_parent_terminate_func(self.__terminate__)

		# Register call: Accessing a dll
		self.server.register_function(self.__access_dll__, 'access_dll')
		# Call routine with parameters and, optionally, return value
		self.server.register_function(self.__call_dll_routine__, 'call_dll_routine')
		# Register call: Registering arguments and return value types
		self.server.register_function(self.__register_argtype_and_restype__, 'register_argtype_and_restype')
		# Register call: Registering dll calls
		self.server.register_function(self.__register_routine__, 'register_routine')
		# Register destructur: Call goes into xmlrpc-server first, which then terminates parent
		self.server.register_function(self.server.shutdown, 'terminate')

		# Status log
		self.log.out('[_server_] ctypes server is listening on port %d.' % self.p['port_server_ctypes'])
		self.log.out('[_server_] STARTED.')
		self.log.out('[_server_] Serve forever ...')

		# Run server ...
		self.server.serve_forever()


	def __access_dll__(self, full_path_dll, full_path_dll_unix, dll_name, dll_type):

		# Although this should happen only once per dll, lets be on the safe side
		if full_path_dll not in self.dll_dict.keys():

			# Log status
			self.log.out('[_server_] Attaching to "%s" of type %s ...' % (dll_name, dll_type))
			self.log.out('[_server_]  (%s)' % full_path_dll)

			try:

				# Load library TODO do this for different types of dlls (cdll, oledll)
				self.dll_dict[full_path_dll_unix] = {
					'type': dll_type,
					'name': dll_name,
					'full_path': full_path_dll,
					'dll_handler': ctypes.windll.LoadLibrary(full_path_dll),
					'method_handlers': {}
					}

				# Log status
				self.log.out('[_server_] ... done.')

				return 1 # Success

			except:

				# Log status
				self.log.out('[_server_] ... failed! Traceback:')

				# Push traceback to log
				self.log.out(traceback.format_exc())

				return 0 # Fail

		# Just in case
		return 1


	def __call_dll_routine__(self, full_path_dll_unix, routine_name, args, kw):

		# Log status
		self.log.out('[_server_] Trying call routine "%s" ...' % routine_name)

		# Make it shorter ...
		method = self.dll_dict[full_path_dll_unix]['method_handlers'][routine_name]

		# args is passed as a list, must be a tuple
		args = tuple(args)

		# Default return value
		return_value = '__none_value__'

		# This is risky
		try:

			# Call into dll # TODO structs and pointers
			if method.restype == ctypes.c_void_p:
				method(*args, **kw)
			else:
				return_value = method(*args, **kw)

			# Log status
			self.log.out('[_server_] ... done.')

		except:

			# Log status
			self.log.out('[_server_] ... failed! Traceback:')

			# Push traceback to log
			self.log.out(traceback.format_exc())

		# Return result
		return return_value


	def __register_argtype_and_restype__(self, full_path_dll_unix, routine_name, argtypes, restype):

		# Log status
		self.log.out('[_server_] Trying to set argument and return value types for "%s" ...' % routine_name)

		# Make it shorter ...
		method = self.dll_dict[full_path_dll_unix]['method_handlers'][routine_name]

		# Start list for argtypes
		tmp_argtypes = []

		# Iterate over argtype strings and parse them into ctypes TODO handle structs
		for arg_str in argtypes:

			# Try the easy way first ...
			try:

				# Evaluate string. Does not work for pointers and structs
				tmp_argtypes.append(eval(arg_str))

			# And now the hard stuff ...
			except:

				# Push traceback to log
				self.log.out(traceback.format_exc())

				# TODO

		# Set argtypes in routine object
		method.argtypes = tmp_argtypes

		# Set return value type, easy ...
		try:

			# Evaluate return value type string
			method.restype = eval(restype)

		# And now the hard way ...
		except:

			# TODO
			method.restype = ctypes.c_void_p # HACK assume void

		# Log status
		self.log.out('[_server_] ... done.')

		# Log status
		self.log.out('[_server_] Routine "%s" argtypes: %s' % (routine_name, pf(method.argtypes)))
		self.log.out('[_server_] Routine "%s" restype: %s' % (routine_name, pf(method.restype)))

		return 1 # Success


	def __register_routine__(self, full_path_dll_unix, routine_name):

		# Log status
		self.log.out('[_server_] Trying to access "%s"' % routine_name)

		try:

			# Just in case this routine is already known
			if routine_name not in self.dll_dict[full_path_dll_unix]['method_handlers'].keys():

				# Get handler on routine in dll
				self.dll_dict[full_path_dll_unix]['method_handlers'][routine_name] = getattr(
					self.dll_dict[full_path_dll_unix]['dll_handler'], routine_name
					)

			# Log status
			self.log.out('[_server_] ... done.')

			return 1 # Success

		except:

			# Log status
			self.log.out('[_server_] ... failed! Traceback:')

			# Push traceback to log
			self.log.out(traceback.format_exc())

			return 0 # Fail


	def __terminate__(self):

		# Run only if session still up
		if self.up:

			# Status log
			self.log.out('[_server_] TERMINATING ...')

			# Terminate log
			self.log.terminate()

			# Status log
			self.log.out('[_server_] TERMINATED.')

			# Session down
			self.up = False


# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# INIT
# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

if __name__ == '__main__':

	# Parse arguments comming from unix side
	parser = argparse.ArgumentParser()
	parser.add_argument(
		'--id', type = str, nargs = 1
		)
	parser.add_argument(
		'--port_server_ctypes', type = int, nargs = 1
		)
	parser.add_argument(
		'--dir_socket_log_main', type = str, nargs = 1
		)
	parser.add_argument(
		'--log_level', type = int, nargs = 1
		)
	args = parser.parse_args()

	# Generate parameter dict
	parameter = {
		'id': args.id[0],
		'platform': 'WINE',
		'stdout': False,
		'stderr': False,
		'logwrite': True,
		'remote_log': True,
		'log_level': args.log_level[0],
		'log_server': False,
		'port_server_ctypes': args.port_server_ctypes[0],
		'dir_socket_log_main': args.dir_socket_log_main[0]
		}

	# Fire up wine server session with parsed parameters
	session = wine_server_class(parameter['id'], parameter)
