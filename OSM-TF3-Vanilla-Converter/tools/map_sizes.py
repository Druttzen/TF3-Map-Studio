"""TF3 build 25533170 desktop map presets (256 metres per terrain tile).

Names/formats: base/mod.json. Tile counts: getNumTiles() in
gui/menu/new_game_or_map_settings_page.tl. Keep the game's lookup values,
including formats whose actual dimensions differ from the advertised ratio.
"""
CUSTOM = 'Custom dimensions'
FORMATS = ('1:1', '1:2', '1:3', '1:4', '1:5')
TILES = {
    'Tiny': ((16,16),(10,20),(8,24),(8,24),(6,30)),
    'Small': ((32,32),(22,44),(18,54),(16,54),(14,70)),
    'Medium': ((44,44),(32,64),(26,78),(22,88),(20,100)),
    'Large': ((56,56),(40,80),(32,96),(28,112),(24,126)),
    'Very Large': ((64,64),(44,88),(36,108),(32,128),(28,140)),
    'Huge': ((80,80),(56,112),(46,138),(40,160),(34,170)),
    'Megalomaniac': ((96,96),(66,132),(54,162),(48,192),(42,210)),
    'Gigantomaniac': ((112,112),(80,160),(64,192),(56,224),(50,250)),
}
SIZES = tuple(TILES)


def dimensions(size, map_format):
    if size not in TILES or map_format not in FORMATS:
        raise ValueError('Choose a TF3 map size and format from the lists.')
    return tuple(n * 256 for n in TILES[size][FORMATS.index(map_format)])


def experimental(size, map_format):
    return size in ('Tiny','Huge','Megalomaniac','Gigantomaniac') or map_format in ('1:4','1:5')


def matching_preset(size):
    """Infer the first matching game preset for older dimension-only profiles."""
    for name in SIZES:
        for map_format in FORMATS:
            if tuple(size) == dimensions(name, map_format):
                return {'size':name, 'format':map_format}
    return None


def validate_preset(preset, size):
    if preset is None:
        return
    if not isinstance(preset,dict) or set(preset) != {'size','format'}:
        raise ValueError('Profile map preset must contain a TF3 size and format.')
    if not isinstance(preset['size'],str) or not isinstance(preset['format'],str):
        raise ValueError('Profile map preset names must be text.')
    if dimensions(preset['size'],preset['format']) != tuple(size):
        raise ValueError('Profile map dimensions do not match its TF3 preset.')
