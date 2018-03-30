# -*- coding: utf-8 -*-

"""

ZUGBRUECKE
Calling routines in Windows DLLs from Python scripts running on unixlike systems
https://github.com/pleiszenburg/zugbruecke

	src/zugbruecke/core/data/mem_contents.py: (Un-) packing of memory

	Required to run on platform / side: [UNIX, WINE]

	Copyright (C) 2017-2018 Sebastian M. Ernst <ernst@pleiszenburg.de>

<LICENSE_BLOCK>
The contents of this file are subject to the GNU Lesser General Public License
Version 2.1 ("LGPL" or "License"). You may not use this file except in
compliance with the License. You may obtain a copy of the License at
https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt
https://github.com/pleiszenburg/zugbruecke/blob/master/LICENSE

Software distributed under the License is distributed on an "AS IS" basis,
WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License for the
specific language governing rights and limitations under the License.
</LICENSE_BLOCK>

"""


# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# IMPORT
# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

import ctypes
from pprint import pformat as pf
#import traceback

from ..const import GROUP_VOID
from ..memory import (
	generate_pointer_from_bytes,
	overwrite_pointer_with_bytes,
	serialize_pointer_into_bytes
	)

WCHAR_BYTES = ctypes.sizeof(ctypes.c_wchar)


# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# CLASS: Memory content packing and unpacking
# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

class memory_contents_class():


	def apply_memsync_to_argtypes_definition(self, memsync_d_list, argtypes_d):

		# Iterate over memory segments, which must be kept in sync
		for memsync_d in memsync_d_list:

			# Get type of pointer argument
			arg_type = self.__get_argument_type_by_memsync_path__(memsync_d['p'], argtypes_d)

			# HACK make memory sync pointers type agnostic
			arg_type['g'] = GROUP_VOID
			arg_type['t'] = None # no type string


	def client_pack_memory_list(self, args_tuple, memsync_d_list):

		# Pack data for every pointer, append data to package
		return [self.__pack_memory_item__(args_tuple, memsync_d) for memsync_d in memsync_d_list]


	def client_unpack_memory_list(self, args_list, mem_package_list, memsync_d_list):

		# Iterate over memory package dicts
		for memory_d, memsync_d in zip(mem_package_list, memsync_d_list):

			# If pointer was passed as a Null pointer
			if memory_d['_a'] is None:

				# Unpack one memory section / item
				self.__unpack_memory_item_data__(args_list, memory_d, memsync_d)

			# If pointer pointed to data
			else:

				# Swap local and remote memory addresses
				self.__swap_memory_addresses__(memory_d)

				# Adjust Unicode wchar length
				if memsync_d['w']:
					self.__adjust_wchar_length__(memory_d)

				# Overwrite the local pointers with new data
				overwrite_pointer_with_bytes(
					ctypes.c_void_p(memory_d['a']),
					memory_d['d']
					)


	def server_pack_memory_list(self, args_list, mem_package_list, memsync_d_list):

		# Iterate through pointers and serialize them
		for memory_d, memsync_d in zip(mem_package_list, memsync_d_list):

			# If pointer was passed as a Null pointer
			if memory_d['a'] is None:

				memory_d.update(self.__pack_memory_item__(args_list, memsync_d))

			# If pointer pointed to data
			else:

				# Overwrite old data in package with new data from memory
				memory_d['d'] = serialize_pointer_into_bytes(
					ctypes.c_void_p(memory_d['a']), memory_d['l']
					)


	def server_unpack_memory_list(self, args_tuple, arg_memory_list, memsync_d_list):

		# Iterate over memory segments, which must be kept in sync
		for memory_d, memsync_d in zip(arg_memory_list, memsync_d_list):

			# Is this a null pointer?
			if memory_d['a'] is None:

				# Insert new NULL pointer
				self.__unpack_memory_item_null__(args_tuple, memory_d, memsync_d)

			else:

				# Unpack one memory section / item
				self.__unpack_memory_item_data__(args_tuple, memory_d, memsync_d)


	def __adjust_wchar_length__(self, memory_d):

		old_len = memory_d['w']
		new_len = WCHAR_BYTES

		if old_len == new_len:
			return

		tmp = bytearray(memory_d['l'] * new_len // old_len)

		for index in range(old_len if new_len > old_len else new_len):
			tmp[index::new_len] = memory_d['d'][index::old_len]

		memory_d['d'] = bytes(tmp)
		memory_d['l'] = len(memory_d['d'])
		memory_d['w'] = WCHAR_BYTES


	def __get_argument_by_memsync_path__(self, args_tuple, memsync_path):

		# Reference args_tuple as initial value
		element = args_tuple

		# Step through path
		for path_element in memsync_path:

			# Go deeper ...
			if isinstance(path_element, int):
				if path_element < 0: # Pointer to pointer for memory allocation by DLL
					element = self.__item_pointer_strip__(element)
				else: # Dive into argument tuple
					element = element[path_element]
			else: # Dive into struct
				element = getattr(self.__item_pointer_strip__(element), path_element)

		return element


	def __get_argument_type_by_memsync_path__(self, memsync_path, argtypes_d):

		# Reference processed argument types - start with depth 0
		arg_type = argtypes_d[memsync_path[0]]

		# Step through path to argument type ...
		for path_element in memsync_path[1:]:
			# Continue on special flags HACK
			if isinstance(path_element, int):
				if path_element < 0:
					continue
			# Go deeper ...
			arg_type = {field['n']: field for field in arg_type['_fields_']}[path_element]

		return arg_type


	def __get_number_of_elements__(self, args_tuple, memsync_d):

		# There is no function defining the length?
		if '_f' not in memsync_d.keys():

			# Search for length
			length = self.__get_argument_by_memsync_path__(args_tuple, memsync_d['l'])

			# Length might come from ctypes or a Python datatype
			return getattr(length, 'value', length)

		# Make sure length can be computed from a tuple of arguments
		assert isinstance(memsync_d['l'], tuple)

		# Compute length from arguments and return
		return memsync_d['_f'](*(
			self.__get_argument_by_memsync_path__(args_tuple, item) for item in memsync_d['l']
			))


	def __pack_memory_item__(self, args_tuple, memsync_d):

		# Search for pointer
		pointer = self.__get_argument_by_memsync_path__(args_tuple, memsync_d['p'])

		# Compute actual length
		length = self.__get_number_of_elements__(args_tuple, memsync_d) * memsync_d['s']

		# Convert argument into ctypes datatype TODO more checks needed!
		if '_c' in memsync_d.keys():
			pointer = ctypes.pointer(memsync_d['_c'].from_param(pointer))

		return {
			'd': serialize_pointer_into_bytes(pointer, length), # serialized data, '' if NULL pointer
			'l': length, # length of serialized data
			'a': ctypes.cast(pointer, ctypes.c_void_p).value, # local pointer address as integer
			'_a': None, # remote pointer has not been initialized
			'w': WCHAR_BYTES if memsync_d['w'] else None # local length of Unicode wchar if required
			}


	def __swap_memory_addresses__(self, memory_d):

		memory_d.update({
			'a': memory_d.get('_a', None),
			'_a': memory_d.get('a', None)
			})


	def __unpack_memory_item_data__(self, args_tuple, memory_d, memsync_d):

		# Swap local and remote memory addresses
		self.__swap_memory_addresses__(memory_d)

		# Search for pointer in passed arguments
		pointer_arg = self.__get_argument_by_memsync_path__(args_tuple, memsync_d['p'][:-1])

		# Adjust Unicode wchar length
		if memsync_d['w']:
			self.__adjust_wchar_length__(memory_d)

		# Generate pointer to passed data
		pointer = generate_pointer_from_bytes(memory_d['d'])

		# HACK Is this a pointer?
		if hasattr(pointer_arg, 'contents'):
			# Is the pointer pointing to another pointer?
			if hasattr(pointer_arg.contents, 'value'):
				# Is the pointer empty?
				if pointer_arg.contents.value is None:
					# Overwrite the pointer's value
					pointer_arg.contents.value = pointer.value
					# Get out of here HACK
					return

		# If we're in the top level arguments or an array ...
		if isinstance(memsync_d['p'][-1], int):
			# Handle deepest instance (exchange element in list/tuple) HACK
			pointer_arg[memsync_d['p'][-1]] = pointer
		# If we're at a field of a struct
		else:
			# Handle deepest instance
			setattr(pointer_arg.contents, memsync_d['p'][-1], pointer)

		# Store the server's memory address
		memory_d['a'] = pointer.value


	def __unpack_memory_item_null__(self, args_tuple, memory_d, memsync_d):

		# Swap local and remote memory addresses
		self.__swap_memory_addresses__(memory_d)

		# Make sure this is a pointer to a pointer
		assert memsync_d['p'][-1] == -1

		# Search for pointer in passed arguments
		pointer_arg = self.__get_argument_by_memsync_path__(args_tuple, memsync_d['p'][:-2])

		# Generate empty pointer
		pointer = ctypes.pointer(ctypes.c_void_p())

		# If we're in the top level arguments or an array ...
		if isinstance(memsync_d['p'][-2], int):
			# Handle deepest instance (exchange element in list/tuple) HACK
			pointer_arg[memsync_d['p'][-2]] = pointer
		# If we're at a field of a struct
		else:
			# Handle deepest instance
			setattr(pointer_arg.contents, memsync_d['p'][-1], pointer)
