datadir = get_option('datadir')
desktop_file_validate = find_program('desktop-file-validate', required: false)
appstreamcli = find_program('appstreamcli', required: false)

foreach name : [app_id, app_id + '.Terminal']
  desktop_file = configure_file(
    input: name + '.desktop.in',
    output: name + '.desktop',
    configuration: {'bindir': bindir},
    install: true,
    install_dir: datadir / 'applications',
  )
  if desktop_file_validate.found()
    test('validate ' + name + '.desktop', desktop_file_validate, args: [desktop_file])
  endif
endforeach

metainfo = files(app_id + '.metainfo.xml')
install_data(metainfo, install_dir: datadir / 'metainfo')
if appstreamcli.found()
  test('validate metainfo', appstreamcli, args: ['validate', '--no-net', '--explain', metainfo])
endif

install_data(app_id + '.mime.xml', rename: app_id + '.xml', install_dir: datadir / 'mime' / 'packages')

install_data(app_id + '.svg', install_dir: datadir / 'icons' / 'hicolor' / 'scalable' / 'apps')
install_data(app_id + '.svg', rename: mime_type.replace('/', '-') + '.svg',
  install_dir: datadir / 'icons' / 'hicolor' / 'scalable' / 'mimetypes')
