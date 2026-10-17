datadir = get_option('datadir')
desktop_file_validate = find_program('desktop-file-validate', required: false)
appstreamcli = find_program('appstreamcli', required: false)
po_dir = meson.project_source_root() / 'po'

foreach name : [app_id, app_id + '.Terminal']
  desktop_file = i18n.merge_file(
    input: configure_file(input: name + '.desktop.in', output: name + '.desktop.in', configuration: {'bindir': bindir}),
    output: name + '.desktop',
    type: 'desktop',
    po_dir: po_dir,
    install: true,
    install_dir: datadir / 'applications',
  )
  if desktop_file_validate.found()
    test('validate ' + name + '.desktop', desktop_file_validate, args: [desktop_file])
  endif
endforeach

metainfo = i18n.merge_file(
  input: app_id + '.metainfo.xml',
  output: app_id + '.metainfo.xml',
  po_dir: po_dir,
  install: true,
  install_dir: datadir / 'metainfo',
)
if appstreamcli.found()
  test('validate metainfo', appstreamcli, args: ['validate', '--no-net', '--explain', metainfo])
endif

install_data(app_id + '.mime.xml', rename: app_id + '.xml', install_dir: datadir / 'mime' / 'packages')

install_data(app_id + '.svg', install_dir: datadir / 'icons' / 'hicolor' / 'scalable' / 'apps')
install_data(app_id + '-symbolic.svg', install_dir: datadir / 'icons' / 'hicolor' / 'symbolic' / 'apps')

install_man('vcvplugin-install.1')
