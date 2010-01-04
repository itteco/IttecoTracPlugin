import unittest

from itteco.calendar.tests import api, rpc

def suite():
    suite = unittest.TestSuite()
    suite.addTest(api.suite())
    suite.addTest(rpc.suite())
    return suite

if __name__ == '__main__':
    unittest.main(defaultTest='suite')
