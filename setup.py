try:
    from ez_setup import use_setuptools
    use_setuptools()
except ImportError:
    pass #Is installing from a source package is not copied locally
from setuptools import setup, find_packages

from itteco import __package__, __version__

setup(
    name=__package__,
    version=__version__,
    author='Itteco.com',
    url='http://www.itteco.com/',
    description='Itteco Trac Plugin.',
    license='MIT',
    packages=find_packages(),
    package_data={
        'itteco': ['templates/*', 'htdocs/images/*', 'htdocs/css/*.css', 
            'htdocs/css/jquery.ui/themes/flora/*.css', 
            'htdocs/css/jquery.ui/themes/flora/i/*', 
            'htdocs/js/jquery.ui/*','htdocs/js/*.js', 
            'htdocs/charts/amstock/*.swf'],
                  'itteco.config': ["*.ini"]},
    entry_points = {'trac.plugins': ['itteco.init = itteco.init',
                                     'itteco.scrum.api = itteco.scrum.api',
                                     'itteco.scrum.web_ui = itteco.scrum.web_ui',
                                     'itteco.scrum.burndown = itteco.scrum.burndown',
                                     'itteco.ticket.admin = itteco.ticket.admin',
                                     'itteco.ticket.report = itteco.ticket.report',
                                     'itteco.ticket.roadmap = itteco.ticket.roadmap',
                                     'itteco.ticket.web_ui = itteco.ticket.web_ui']},
    install_requires=['trac >= 0.11.3','genshi >= 0.5.1'], 
)
