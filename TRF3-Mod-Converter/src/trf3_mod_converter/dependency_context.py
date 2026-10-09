"""Keep imported descriptors bound to their authors' resources and locales."""
from dataclasses import replace, is_dataclass
import hashlib
import json
from pathlib import Path

from .lua_metadata import TranslatedString
from .resource_profiles import TranslatedConcat, load_resource_table
from .workshop_resources import WorkshopResources


class DependencyContext:
    def __init__(self, source, initial, translations, audit, fingerprints):
        self.source = source
        self.lookups = {source:initial}
        self.owners = [source]
        self.translations, self.audit, self.fingerprints = translations, audit, fingerprints
        self.archive = {}
        self.locales = {}

    def lookup(self, reference, kind, *, owners=None, allow_global=True):
        matches = []
        for owner in sorted(set(owners or self.owners)):
            if owner not in self.lookups:
                self.lookups[owner] = WorkshopResources(owner)
            match = self.lookups[owner].resolve(reference, kind, prefer_local=owner != self.source,
                                               allow_global=allow_global)
            if match is not None:
                matches.append(match)
        if len({match['sha256'] for match in matches}) > 1:
            raise ValueError(f'Conflicting resource contents in dependency author contexts: {kind} {reference}')
        return matches

    def record(self, matches, target, policy, *, original_file=None):
        rows = self.audit.setdefault('workshopDependencies', [])
        for match in matches:
            for path, digest in match['fingerprints'].items():
                if path in self.fingerprints and self.fingerprints[path] != digest:
                    raise ValueError(f'Workshop dependency changed during adaptation: {path}')
                self.fingerprints[path] = digest
            row = {key:match[key] for key in ('kind','sourceReference','providers','sha256',
                'declarationFingerprints','providerSelection','lookupSource','lookupPolicy','originFingerprints')}
            row.update(policy=policy, nativeTest='not_run')
            if target is not None:
                row['targetReference'] = target
            if original_file is not None:
                row['originalFile'] = original_file
            if row not in rows:
                rows.append(row)

    def record_absence(self, reference, kind, owners=None):
        rows = self.audit.setdefault('workshopAbsentDependencies', [])
        for owner in sorted(set(owners or self.owners)):
            if owner not in self.lookups:
                self.lookups[owner] = WorkshopResources(owner)
            row = self.lookups[owner].absence(reference, kind, prefer_local=owner != self.source)
            if row not in rows:
                rows.append(row)
        return rows

    def provider_owners(self, matches):
        return sorted({self.source.parent/Path(provider).relative_to(self.source.parent).parts[0]
                       for match in matches for provider in match['providers']})

    def localize(self, data, owners):
        if owners == [self.source]:
            return data
        keys = set()
        def gather(value):
            if isinstance(value, TranslatedConcat):
                keys.update(part for translated, part in value.parts if translated)
            elif isinstance(value, TranslatedString):
                keys.add(str(value))
            elif isinstance(value, dict):
                for key, item in value.items():
                    gather(key); gather(item)
            elif isinstance(value, list):
                for item in value: gather(item)
            elif is_dataclass(value):
                for item in vars(value).values(): gather(item)
        gather(data)
        if not keys:
            return data
        locale_tables = []
        for owner in owners:
            if owner not in self.locales:
                matches = self.lookup('strings.lua', 'localization', owners=[owner])
                if not matches:
                    raise ValueError(f'Localized Workshop descriptor has no verifiable author strings.lua: {owner.name}')
                match = matches[0]
                table = load_resource_table(match['data'].decode('utf-8-sig'), allow_global_literals=True,
                    audit=self.audit, resource=f'_dependencies/{owner.name}/strings.lua')
                if not isinstance(table, dict) or any(not isinstance(lang, str) or not lang
                        or not isinstance(values, (dict, list)) or (isinstance(values, list) and values)
                        or (isinstance(values, dict) and any((not isinstance(k, str) and not (type(k) is int and k >= 1))
                                                           or not isinstance(v, str) for k,v in values.items()))
                        for lang,values in table.items()):
                    raise ValueError('Workshop dependency localization needs named language/key/text tables')
                archive = f'_dependencies/{owner.name}/strings.lua'
                normalized = {}
                for lang, values in table.items():
                    normalized[lang] = {}
                    for key, value in values.items() if isinstance(values, dict) else []:
                        if isinstance(key, str):
                            normalized[lang][key] = value
                        else:
                            self.audit.setdefault('translationMigrations', []).append({
                                'language':lang, 'sourceKey':key, 'sourceValue':value,
                                'policy':'archive_unattached_numeric_translation_entry',
                                'originalFile':'_port_originals/'+archive, 'nativeTest':'not_run'})
                table = normalized
                self.archive[archive] = match['data']
                self.record(matches, None, 'namespace_author_dependency_localization',
                            original_file='_port_originals/'+archive)
                self.locales[owner] = table
            locale_tables.append(self.locales[owner])
        if any(table != locale_tables[0] for table in locale_tables[1:]):
            raise ValueError('Identical Workshop descriptors have different author localization; declare the intended provider')
        source_table = locale_tables[0]
        prefix = 'tf2_dep_'+hashlib.sha256(json.dumps([str(owner) for owner in owners]).encode()).hexdigest()[:16]+'_'
        languages = set(self.translations) | set(source_table) | {'en'}
        for language in sorted(languages):
            target = self.translations.setdefault(language, {})
            for key in sorted(keys):
                value = source_table.get(language, {}).get(key, key)
                new_key = prefix+key
                if new_key in target and target[new_key] != value:
                    raise ValueError('Dependency localization namespace collides with authored translations')
                target[new_key] = value
        def rename(value):
            if isinstance(value, TranslatedConcat):
                return TranslatedConcat(tuple((flag,prefix+part if flag else part) for flag,part in value.parts))
            if isinstance(value, TranslatedString):
                return TranslatedString(prefix+str(value))
            if isinstance(value, dict):
                return {rename(key):rename(item) for key,item in value.items()}
            if isinstance(value, list):
                return [rename(item) for item in value]
            if is_dataclass(value):
                return replace(value, **{key:rename(item) for key,item in vars(value).items()})
            return value
        return rename(data)
