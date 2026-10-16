project('vcvplugin-installer',
  version: files('vcvplugin/VERSION'),
  license: 'GPL-3.0-or-later',
  meson_version: '>= 1.0',
)

app_id = 'io.github.un1tz3r0.VcvPluginInstaller'
mime_type = 'application/x-vcvplugin'

python = import('python').find_installation('python3')
if not python.language_version().version_compare('>= 3.11')
  error('Python 3.11 or newer is required, found ' + python.language_version())
endif

bindir = get_option('prefix') / get_option('bindir')
pkgdatadir = get_option('prefix') / get_option('datadir') / meson.project_name()

# The package goes into a private directory that the launchers put on sys.path.
install_data(
  'vcvplugin/__init__.py',
  'vcvplugin/__main__.py',
  'vcvplugin/cli.py',
  'vcvplugin/core.py',
  'vcvplugin/gui.py',
  'vcvplugin/VERSION',
  install_dir: pkgdatadir / 'vcvplugin',
)

foreach launcher : [['vcvplugin-install', 'cli'], ['vcvplugin-gui', 'gui']]
  configure_file(
    input: 'build-aux/launcher.in',
    output: launcher[0],
    configuration: {'PYTHON': python.full_path(), 'pkgdatadir': pkgdatadir, 'module': launcher[1]},
    install: true,
    install_dir: get_option('bindir'),
    install_mode: 'rwxr-xr-x',
  )
endforeach

subdir('data')

import('gnome').post_install(
  gtk_update_icon_cache: true,
  update_desktop_database: true,
  update_mime_database: true,
)
