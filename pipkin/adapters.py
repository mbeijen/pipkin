import os.path
from abc import ABC, abstractmethod
from logging import getLogger
from typing import Optional, List, Dict, Tuple

from pipkin.util import parse_meta_dir_name

META_ENCODING = "utf-8"

logger = getLogger(__name__)


class Adapter(ABC):
    @abstractmethod
    def get_user_packages_path(self) -> Optional[str]:
        """Unix / Windows ports return the location of user packages"""
        ...

    @abstractmethod
    def get_default_target(self) -> str:
        """Installation location if neither --user nor --target is specified"""
        ...

    @abstractmethod
    def list_dists(self, paths: List[str] = None) -> Dict[str, Tuple[str, str]]:
        """Return canonic names of the distributions mapped to their meta dir names and
        installation paths.

        If a distribution is installed to different sys.path locations, then return only the first one.
        """
        ...

    @abstractmethod
    def remove_dist(
        self, dist_name: str, target: Optional[str] = None, above_target: bool = False
    ) -> None:
        """If target is given, then remove from this directory.
        If above_path, then also remove from sys.path dirs which would hide the package at path.
        Otherwise remove the first visible instance of the dist according to sys.path.
        """
        ...

    @abstractmethod
    def read_file(self, path: str) -> bytes:
        """Path must be device's absolute path (ie. start with /)"""
        ...

    @abstractmethod
    def write_file(self, path: str, content: bytes) -> None:
        """Path must be device's absolute path (ie. start with /)"""
        ...

    @abstractmethod
    def join_path(self, *parts: str) -> str:
        ...

    @abstractmethod
    def split_dir_and_basename(self, path: str) -> Tuple[str, str]:
        ...

    @abstractmethod
    def create_dir_if_doesnt_exist(self, path: str) -> None:
        ...


class BaseAdapter(Adapter, ABC):
    @abstractmethod
    def get_sys_path(self) -> List[str]:
        ...

    @abstractmethod
    def remove_file(self, path: str) -> None:
        ...

    @abstractmethod
    def remove_dir_if_empty(self, path: str) -> None:
        ...

    @abstractmethod
    def list_meta_dir_names(self, path: str, dist_name: Optional[str] = None) -> List[str]:
        """Return meta dir names from the indicated directory"""
        ...

    def get_default_target(self) -> str:
        for entry in self.get_sys_path():
            if "lib" in entry:
                return entry
        raise AssertionError("Could not determine default target")

    def list_dists(self, paths: List[str] = None) -> Dict[str, Tuple[str, str]]:
        if not paths:
            paths = [entry for entry in self.get_sys_path() if entry != ""]

        result = {}
        for path in paths:
            for dir_name in self.list_meta_dir_names(path):
                dist_name, _ = parse_meta_dir_name(dir_name)
                if dist_name not in result:
                    result[dist_name] = dir_name, path

        return result

    def remove_dist(
        self, dist_name: str, target: Optional[str] = None, above_target: bool = False
    ) -> None:
        could_remove = False
        if target:
            result = self.check_remove_dist_from_path(dist_name, target)
            could_remove = could_remove or result
            if above_target and target in self.get_sys_path():
                for entry in self.get_sys_path():
                    if entry == "":
                        continue
                    elif entry == target:
                        break
                    else:
                        result = self.check_remove_dist_from_path(dist_name, entry)
                        could_remove = could_remove or result

        else:
            for entry in self.get_sys_path():
                if entry == "":
                    continue
                else:
                    result = self.check_remove_dist_from_path(dist_name, entry)
                    could_remove = could_remove or result
                    if result:
                        break

        if not could_remove:
            logger.warning("Could not find %r for removing", dist_name)

    def check_remove_dist_from_path(self, dist_name: str, path: str) -> bool:
        meta_dirs = self.list_meta_dir_names(path, dist_name)
        result = False
        for meta_dir_name in meta_dirs:
            self.remove_dist_by_meta_dir(path, meta_dir_name)
            result = True

        return result

    def remove_dist_by_meta_dir(self, containing_dir: str, meta_dir_name: str) -> None:
        record_bytes = self.read_file(self.join_path(containing_dir, meta_dir_name, "RECORD"))
        record_lines = record_bytes.decode(META_ENCODING).splitlines()

        dirs = set()
        for line in record_lines:
            rel_path, _, _ = line.split(",")
            abs_path = self.join_path(containing_dir, rel_path)
            self.remove_file(abs_path)
            abs_dir, _ = self.split_dir_and_basename(abs_path)
            dirs.add(abs_dir)

        for abs_dir in dirs:
            self.remove_dir_if_empty(abs_dir)

    def join_path(self, *parts: str) -> str:
        assert parts
        return "/".join(parts)

    def split_dir_and_basename(self, path: str) -> Tuple[str, str]:
        dir_name, basename = path.rsplit("/", maxsplit=1)
        return dir_name, basename


class InterpreterAdapter(BaseAdapter, ABC):
    """Base class for adapters, which communicate with an interpreter"""

    ...


class BareMetalAdapter(InterpreterAdapter, ABC):
    ...


class SerialAdapter(BareMetalAdapter):
    ...


class WebReplAdapter(BareMetalAdapter):
    ...


class ExecutableAdapter(InterpreterAdapter, ABC):
    ...


class LocalExecutableAdapter(ExecutableAdapter):
    ...


class SshExecutableAdapter(ExecutableAdapter):
    ...


class LocalMirrorAdapter(BaseAdapter, ABC):
    def __init__(self, base_path: str):
        self.base_path = base_path

    def get_user_packages_path(self) -> Optional[str]:
        return None

    def read_file(self, path: str) -> bytes:
        local_path = self.convert_to_local_path(path)
        assert os.path.isfile(local_path)
        with open(local_path, "rb") as fp:
            return fp.read()

    def write_file(self, path: str, content: bytes) -> None:
        local_path = self.convert_to_local_path(path)
        assert not os.path.isdir(local_path)

        with open(local_path, "wb") as fp:
            # TODO: write in blocks and sync
            fp.write(content)

    def remove_file(self, path: str) -> None:
        local_path = self.convert_to_local_path(path)
        assert os.path.isfile(local_path)
        os.remove(local_path)

    def remove_dir_if_empty(self, path: str) -> None:
        local_path = self.convert_to_local_path(path)
        assert os.path.isdir(local_path)
        if not os.listdir(local_path):
            os.rmdir(local_path)

    def create_dir_if_doesnt_exist(self, path: str) -> None:
        local_path = self.convert_to_local_path(path)
        if not os.path.isdir(local_path):
            assert not os.path.exists(local_path)
            os.mkdir(local_path, 0o755)

    def convert_to_local_path(self, device_path: str) -> str:
        assert device_path.startswith("/")
        return os.path.normpath(self.base_path + device_path)

    def list_meta_dir_names(self, path: str, dist_name: Optional[str] = None) -> List[str]:
        local_path = self.convert_to_local_path(path)
        return [
            name
            for name in os.listdir(local_path)
            if name.endswith(".dist-info")
            and (dist_name is None or name.startswith(dist_name + "-"))
        ]


class MountAdapter(LocalMirrorAdapter):
    def get_sys_path(self) -> List[str]:
        # TODO: consider /flash/lib and so on
        return ["/lib"]


class DirAdapter(LocalMirrorAdapter):
    def get_sys_path(self) -> List[str]:
        # This means, list command without --path will consider this directory
        return ["/"]

    def get_default_target(self) -> str:
        return "/"


def create_adapter(port: Optional[str]) -> Adapter:
    ...
