# -*- coding: utf-8 -*-
"""
Created on Tue Jun 10 17:53:38 2014

@author: Toberer Lab
"""

import sys
import traceback
import logging
 
def setup_logging_to_file(filename):
    logging.basicConfig( filename=filename,
                         filemode='a',
                         level=logging.DEBUG,
                         format= '%(asctime)s - %(levelname)s - %(message)s',
                       )
 
def extract_function_name():
    """Extracts failing function name from Traceback
 
    by Alex Martelli
    http://stackoverflow.com/questions/2380073/\
    how-to-identify-what-function-call-raise-an-exception-in-python
    """
    tb = sys.exc_info()[-1]
    stk = traceback.extract_tb(tb, 1)
    fname = stk[0][3]
    return fname
 
def log_exception(e):
    logging.error(
    "Function {function_name} raised {exception_class} ({exception_docstring}): {exception_message}".format(
    function_name = extract_function_name(), #this is optional
    exception_class = e.__class__,
    exception_docstring = e.__doc__,
    exception_message = e.message))