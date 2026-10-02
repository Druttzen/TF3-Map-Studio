import json

from trf3_mod_converter.converter import convert_mod, inspect_mod


def test_inspect_json_metadata(tmp_path):
    source = tmp_path / "legacy_mod"
    source.mkdir()
    (source / "mod.json").write_text(json.dumps({
        "name": "Legacy Mod",
        "summary": "A legacy mod",
        "version": 3,
        "authors": [{"name": "Example Author"}],
        "url": "https://example.com"
    }), encoding="utf-8")

    metadata = inspect_mod(source)

    assert metadata.name == "Legacy Mod"
    assert metadata.revision == 3
    assert metadata.target_mod_id == "legacy_mod"


def test_convert_basic_mod(tmp_path):
    source = tmp_path / "legacy_mod"
    source.mkdir()
    (source / "mod.json").write_text(json.dumps({
        "name": "Legacy Mod",
        "authors": [{"name": "Example Author"}],
        "summary": "Example",
        "version": 12
    }), encoding="utf-8")
    (source / "README.txt").write_text("demo", encoding="utf-8")

    destination = tmp_path / "converted_mod"
    report = convert_mod(source, destination)

    assert report["modId"] == "legacy_mod"
    assert (destination / "README.txt").exists()
    mod_json = json.loads((destination / "mod.json").read_text(encoding="utf-8"))
    assert mod_json["modId"] == "legacy_mod"
    assert mod_json["revision"] == 12
    assert json.loads((destination / "_metadata" / "modinfo.json").read_text(encoding="utf-8"))["name"] == "Legacy Mod"


def test_convert_with_overrides(tmp_path):
    source = tmp_path / "legacy_mod"
    source.mkdir()
    (source / "mod.json").write_text(json.dumps({"name": "Legacy Mod", "version": 1}), encoding="utf-8")

    destination = tmp_path / "converted_mod"
    convert_mod(source, destination, name="Renamed Mod", author="New Author")

    mod_json = json.loads((destination / "mod.json").read_text(encoding="utf-8"))
    metadata = json.loads((destination / "_metadata" / "modinfo.json").read_text(encoding="utf-8"))

    assert mod_json["modId"] == "renamed_mod"
    assert metadata["name"] == "Renamed Mod"
    assert metadata["authors"][0]["name"] == "New Author"


def test_generated_metadata_takes_precedence_over_legacy_files(tmp_path):
    source = tmp_path / "legacy_mod"
    source.mkdir()
    (source / "info.json").write_text(
        json.dumps({"name": "Old Name", "description": "Legacy description"}),
        encoding="utf-8",
    )
    (source / "modinfo.json").write_text(json.dumps({"name": "Older Name"}), encoding="utf-8")

    destination = tmp_path / "converted_mod"
    convert_mod(source, destination, name="New")

    assert inspect_mod(destination).name == "New"

    reconverted = tmp_path / "reconverted_mod"
    convert_mod(destination, reconverted)
    assert inspect_mod(reconverted).name == "New"


def test_legacy_metadata_fills_fields_missing_from_generated_metadata(tmp_path):
    source = tmp_path / "mixed_metadata"
    metadata_dir = source / "_metadata"
    metadata_dir.mkdir(parents=True)
    (source / "mod.json").write_text(json.dumps({"modId": "canonical_mod"}), encoding="utf-8")
    (metadata_dir / "modinfo.json").write_text(
        json.dumps({"name": "Canonical Name", "description": "Generated description"}),
        encoding="utf-8",
    )
    (source / "info.json").write_text(
        json.dumps({
            "name": "Legacy Name",
            "description": "Legacy description",
            "summary": "Legacy summary",
            "url": "https://example.com",
        }),
        encoding="utf-8",
    )

    metadata = inspect_mod(source)

    assert metadata.name == "Canonical Name"
    assert metadata.description == "Generated description"
    assert metadata.summary == "Legacy summary"
    assert metadata.url == "https://example.com"


def test_inspect_lua_mod_metadata(tmp_path):
    source = tmp_path / "legacy_tf2_mod"
    source.mkdir()
    (source / "mod.lua").write_text(
        """
        function data()
            return {
                info = {
                    name = _("Pflasterpaket 3"),
                    description = _("modDesc"),
                    severityAdd = "NONE",
                    severityRemove = "WARNING",
                    minorVersion = 4,
                    tags = { "Misc", "Brush" },
                    runFn = "scripts/main.lua",
                    postRunFn = "scripts/post.lua",
                    authors = {
                        {
                            name = "Alpenheuler",
                            role = "CREATOR",
                            tfnetId = 30985,
                            url = "https://www.transportfever.net/wsc/index.php?user/30985-alpenheuler/"
                        }
                    }
                }
            }
        end
        """,
        encoding="utf-8",
    )

    metadata = inspect_mod(source)

    assert metadata.name == "Pflasterpaket 3"
    assert metadata.description == "modDesc"
    assert metadata.revision == 4
    assert metadata.severity_add == "None"
    assert metadata.severity_remove == "Warning"
    assert metadata.tags == ["Misc", "Brush"]
    assert metadata.run_script == "scripts/main.lua"
    assert metadata.post_run_script == "scripts/post.lua"
    assert metadata.authors[0]["name"] == "Alpenheuler"


def test_inspect_direct_lua_file(tmp_path):
    source = tmp_path / "mod.lua"
    source.write_text(
        """
        function data()
            return {
                info = {
                    name = "Direct Lua Mod",
                    description = "From a direct Lua file",
                    authors = {
                        { name = "Tester", role = "CREATOR" }
                    }
                }
            }
        end
        """,
        encoding="utf-8",
    )

    metadata = inspect_mod(source)

    assert metadata.name == "Direct Lua Mod"
    assert metadata.authors[0]["name"] == "Tester"


def test_inspect_lua_return_chunk(tmp_path):
    source = tmp_path / "mod.lua"
    source.write_text(
        """
        return {
            info = {
                name = "Returned Lua Mod",
                description = "A valid returned table",
                authors = { "Lua Author" }
            }
        }
        """,
        encoding="utf-8",
    )

    metadata = inspect_mod(source)

    assert metadata.name == "Returned Lua Mod"
    assert metadata.description == "A valid returned table"
    assert metadata.authors[0]["name"] == "Lua Author"


def test_inspect_lua_bare_table_before_nested_return(tmp_path):
    source = tmp_path / "mod.lua"
    source.write_text(
        '{ name = "Bare", helper = function() return {} end }',
        encoding="utf-8",
    )

    metadata = inspect_mod(source)

    assert metadata.name == "Bare"


def test_inspect_generated_metadata_and_nested_destination(tmp_path):
    source = tmp_path / "legacy_mod"
    source.mkdir()
    (source / "mod.lua").write_text(
        """
        function data()
            return {
                info = {
                    name = "Descriptive Mod",
                    description = "Original description",
                    authors = { "Original Author" },
                    tags = { "Buildings" },
                    url = "https://example.com"
                }
            }
        end
        """,
        encoding="utf-8",
    )

    destination = source / "output"
    convert_mod(source, destination)
    assert not (destination / "output").exists()

    metadata = inspect_mod(destination)
    assert metadata.name == "Descriptive Mod"
    assert metadata.description == "Original description"
    assert metadata.authors[0]["name"] == "Original Author"
    assert metadata.tags == ["Buildings"]
    assert metadata.url == "https://example.com"
    assert metadata.revision == 1
    convert_mod(source, destination, overwrite=True)
    convert_mod(source, destination, overwrite=True)
    assert not (destination / "output").exists()
    assert not (destination / "output").exists()

