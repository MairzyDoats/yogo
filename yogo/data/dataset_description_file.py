import warnings

from ruamel.yaml import YAML
from pathlib import Path
from dataclasses import dataclass

from typing import Any, Dict, Optional

""" I don't *love* the dataset definition that's been defined here anymore.

Here are the issues:
    - 'split fractions' are a part of the definition file, meaning that if we
    want to change the split, we need to change the definition file. This is
    occuring more than expected, so I think it should be separated
    - it's hard to keep track of all the combinations of dataset paths. Looking
    into it this morning, I've found some discrepancies (specifically some
    dataset paths that are missing from a given definition file) that should be
    fixed
    - it's hard to find these discrepancies, since it's just a list of paths. When
    you have > 10, it's difficult for the human brain to find duplicates.
    - `load_dataset_description` is a horrendously long and difficult-to-read
    function. This should be easy to parse!

Things that are good:
    - the 'definition file' method of collecting data is great for modularity and
    organization. I've found myself using this file a lot outside of YOGO, which
    lends credability to it's usefulness.

Potential improvements:
    - recursive definitions: I should be able to list some specific paths in a file
    and reference that file in another. E.g. a "uganda-healthy" dataset definition
    could be imported into a "uganda" dataset definition and another file. This would
    simplify the composition of these files tremendously.
    - test tools: should be able to have a tool to check the validity of dataset
    definitions, such as looking for duplicate paths (perhaps in this file, in an
    'if __main__' block, or maybe in the YOGO cli?)
    - moving split-fractions to YOGO: I'm somewhat undecided. This is a more minor fix
    compared to the above.

------------------------------------------------------------------------------------------------------------------

New Specification
-----------------

Required Fields
-------------

A dataset definition file is a YAML file with a `dataset_paths` key, with a list of dataset
path specifications as values. Dataset specifications are another key-value pair, where
the key is an arbitrary label for humans - it is not used by the parsing code. The value can
be either (a) `defn_path` which points to another definition file to be loaded (a "Literal
Specification"), or (b) an `image_path` and a `label_path` pair (a "Recursive Specification").
All paths are absolute. Here's an example

```yaml
dataset_paths:
    image_and_label_dirs:               # These three lines make up one Dataset Specification
        image_path: /path/to/images     # This Dataset Specification is a "Literal Specification"
        label_path: /path/to/labels     # since it defines the actual image and label paths
    another dataset_defn:                                # These two lines make up another Dataset Specification.
        defn_path: /path/to/another/dataset_defn.yml     # This Dataset Specification is a "Recursive Specification".

# the composition of each of the Dataset Specifications above gives a full Dataset Definition.
```

Note: the ability to specify another dataset definition within a dataset definition has some
restrictions. The dataset definition specifcation is a graph, where the nodes are Dataset
Definitions. Edges are directed, and are from the Definition to the Definitions that it defines.
For practical reasons, we can't accept arbitrary graph definitions. For example, if the
specification has a cycle, we will have to reject it (only trees are allowed). We'll also
choose to use unique paths - that is, for any Dataset Definition in our tree, there exists
only one path to it. This'll make it easier keep track of folders. Stricter == Better. Essentially,
we're defining a Tree ( https://en.wikipedia.org/wiki/Tree_(graph_theory) ).

Optional Fields
---------------

Optional fields include:
    - classes: a list of class names to be used in the dataset. Conflicting class definitions
    will be rejected.
    - test_paths: similar to dataset_paths, but for the test set. Basically, it's just a way
    to explicitly specify which data is isolated for testing.
    - split_fractions: a dictionary specifying the split fractions for the dataset. Keys can be
    `train`, `val`, and `test`. If `test_paths` is preset, `train` should be left out. The values
    are floats between 0 and 1, and the sum of `split_fractions` should be 1. WILL BE DEPRICATED SOON.
    - thumbnail_augmentation: a dictionary specifying a class name and pointing to a directory
    of thumbnails. Somewhat niche. Ideally we'd have some sort of other "arbitrary metadata"
    specification that could be used for this sort of thing.
"""


class InvalidDatasetDefinitionFile(Exception):
    ...


@dataclass
class LiteralSpecification:
    image_path: Path
    label_path: Path

    @classmethod
    def from_dict(self, dct: dict[str, str]) -> "LiteralSpecification":
        if len(dct) != 2:
            raise InvalidDatasetDefinitionFile(
                f"LiteralSpecification must have two keys; found {len(dct)}"
            )
        elif "image_path" not in dct or "label_path" not in dct:
            defn_path_hint = (
                " 'defn_path' found - this is a coding error, "
                "and itshouldn't happen! blame axel"
            ) if "defn_path" in dct else ""

            raise InvalidDatasetDefinitionFile(
                "LiteralSpecification must have keys 'image_path' and 'label_path'" + defn_path_hint
            )
        else:
            return LiteralSpecification(
                Path(dct["image_path"]), Path(dct["label_path"])
            )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, LiteralSpecification):
            return False
        else:
            return (
                self.image_path == other.image_path
                and self.label_path == other.label_path
            )

    def __hash__(self) -> int:
        return hash((self.image_path, self.label_path))

    def resolve(self) -> dict[str, str]:
        return {"image_path": str(self.image_path), "label_path": str(self.image_path)}


def _extract_single_value(vs: dict[Any, dict[Any, Any]]) -> dict[Any,Any]:
    """ bespoke function to pull apart the yml spec that I've defined
    """
    print(f'{vs=}')
    if len(vs) != 1:
        raise RuntimeError("expected a single value")
    return next(iter(vs.values()))


def _extract_dataset_paths(path: Path) -> list[dict[str, str]]:
    """
    convert list[dict[str,dict[str,str]]] to list[dict[str,str]],
    since the enclosing dict has only 1 kv pair and 1 value
    """
    with open(path, "r") as f:
        yaml = YAML(typ="safe")
        data = yaml.load(f)

    if "dataset_paths" not in data:
        raise InvalidDatasetDefinitionFile(
            f"Missing dataset_paths for definition file at {path}"
        )

    return list(data["dataset_paths"].values())


@dataclass
class DatasetDefinition:
    _dataset_paths: list[LiteralSpecification]
    _test_dataset_paths: list[LiteralSpecification]

    classes: Optional[list[str]]
    thumbnail_augmentation: Optional[Dict[int, Path]]

    @classmethod
    def from_yaml(cls, path: Path) -> "DatasetDefinition":
        """
        The general idea here is that `dataset_paths` has a list of
        dataset specifications, which can be literal or recursive. We'll
        make a list of both, and then try to resolve the recursive specifications.
        We resolve the recursive specifications later so we can
        """
        with open(path, "r") as f:
            yaml = YAML(typ="safe")
            data = yaml.load(f)

        if "dataset_paths" not in data:
            raise InvalidDatasetDefinitionFile(
                f"Missing dataset_paths for definition file at {path}"
            )

        dataset_specs = cls._load_dataset_specifications(data["dataset_paths"].values())

        if "test_paths" in data:
            test_specs = cls._load_dataset_specifications(
                data["test_paths"].values(), exclude_ymls=[path], exclude_specs=dataset_specs
            )
        else:
            test_specs = []

        return DatasetDefinition(
            _dataset_paths=dataset_specs,
            _test_dataset_paths=test_specs,
            classes=data.get("classes", None),
            thumbnail_augmentation=data.get("thumbnail_augmentation", None),
        )

    @staticmethod
    def _load_dataset_specifications(
        specs: list[dict[str, str]],
        exclude_ymls: list[Path] = [],
        exclude_specs: list[LiteralSpecification] = [],
    ) -> list[LiteralSpecification]:
        """
        load the list of dataset specifications into a list
        of LiteralSpecification. Essentially, we try to resolve
        any recursive specifications into literal specifications.

        >>> extract_paths = _extract_dataset_paths(yml_path)

        We also do some checking here for cycles (as defined by
        `exclude_ymls`) or duplicates.

        `exclude_specs` is a list of specifications that
        should be excluded for one reason or another. for example,
        if a literal specifcation is in the training set, you want
        to make sure you exclude it in the testing set.
        """
        literal_defns: list[LiteralSpecification] = []

        for spec in specs:
            if "defn_path" in spec:
                # extract the paths recursively!
                new_yml_file = Path(spec["defn_path"])

                if new_yml_file in exclude_ymls:
                    raise InvalidDatasetDefinitionFile(
                        f"cycle found: {spec['defn_path']} is duplicated"
                    )

                extract_paths = _extract_dataset_paths(Path(new_yml_file))
                print(extract_paths)

                child_specs = DatasetDefinition._load_dataset_specifications(
                    extract_paths,
                    exclude_ymls=[new_yml_file, *exclude_ymls],
                )

                literal_defns.extend(child_specs)
            elif "image_path" in spec and "label_path" in spec:
                # ez case
                literal_defns.append(LiteralSpecification.from_dict(spec))
            else:
                # even easier case
                raise InvalidDatasetDefinitionFile(
                    f"Invalid spec in dataset_paths: {spec}"
                )

        # check that all of our paths are unique
        if len(set(literal_defns + exclude_specs)) != len(literal_defns + exclude_specs):
            # duplicate literal definitions, or one of the literal definitions that we found
            # is in the exclude set. Report them!
            # TODO report which ones are bad <|:^|
            raise InvalidDatasetDefinitionFile("literal definition found in exclude paths!")

        return literal_defns

    @property
    def dataset_paths(self) -> list[dict[str,str]]:
        return [dp.resolve() for dp in self._dataset_paths]

    @property
    def test_dataset_paths(self) -> list[dict[str,str]]:
        return [dp.resolve() for dp in self._test_dataset_paths]

def check_dataset_paths(
    dataset_paths: list[Dict[str, Path]], prune: bool = False
) -> None:
    to_prune: list[int] = []
    for i in range(len(dataset_paths)):
        if not (
            dataset_paths[i]["image_path"].is_dir()
            and dataset_paths[i]["label_path"].is_dir()
            and len(list(dataset_paths[i]["label_path"].iterdir())) > 0
        ):
            if prune:
                warnings.warn(
                    f"image_path or label_path do not lead to a directory, or there are no labels\n"
                    f"image_path={dataset_paths[i]['image_path']}\nlabel_path={dataset_paths[i]['label_path']}"
                )
                to_prune.append(i)
            else:
                raise FileNotFoundError(
                    f"image_path or label_path do not lead to a directory\n"
                    f"image_path={dataset_paths[i]['image_path']}\nlabel_path={dataset_paths[i]['label_path']}"
                )

    # reverse order so we don't move around the to-delete items in the list
    for i in to_prune[::-1]:
        del dataset_paths[i]
