"""File ownership and atomic writes shared by the subtitle workers."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import tempfile


def atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".subforge-write-", dir=str(path.parent))
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def directory_lock(directory: Path):
    """Protect translation checkpoints; the OS releases this lock on exit."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".subforge-translation.lock").open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("Outra tradução está usando esta pasta de saída. Aguarde ou escolha outra pasta.") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@contextmanager
def reserve_output(preferred: Path, replace: bool = False):
    """Reserve a new output name without replacing an earlier result.

    Comportamento:

      replace=False (padrão)
        Nunca sobrescreve: ``Nome.srt``, depois ``Nome_2.srt``, ``Nome_3.srt``...
        É o modo seguro para lotes longos, onde uma reexecução não pode
        destruir uma tradução já revisada.

      replace=True
        Escreve em ``Nome.srt`` publicando por troca atômica no fim. Serve para
        reexecuções do mesmo episódio, que antes acumulavam ``_2``, ``_3``,
        ``_4``... indefinidamente.

    Em ambos os casos um sidecar exclusivo coordena workers concorrentes; um
    sidecar deixado por desligamento forçado faz um novo sufixo ser escolhido,
    em vez de arriscar dado antigo.
    """
    preferred = Path(preferred).resolve()
    preferred.parent.mkdir(parents=True, exist_ok=True)

    if replace:
        lock = preferred.with_name(preferred.name + ".subforge.lock")
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise RuntimeError(
                f"Outra execução está gravando {preferred.name}. Aguarde ou use outra pasta."
            )
        os.close(fd)
        try:
            yield preferred
        finally:
            lock.unlink(missing_ok=True)
        return

    number = 2
    path = preferred
    while True:
        if not path.exists():
            lock = path.with_name(path.name + ".subforge.lock")
            try:
                fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                pass
            else:
                os.close(fd)
                if not path.exists():
                    break
                lock.unlink(missing_ok=True)
        path = preferred.with_name(f"{preferred.stem}_{number}{preferred.suffix}")
        number += 1

    try:
        yield path
    finally:
        lock.unlink(missing_ok=True)


@contextmanager
def temporary_workspace(parent: Path, *, keep: bool = False):
    """Never fall back to the results directory if temporary creation fails."""
    parent = Path(parent).resolve()
    workspace = Path(tempfile.mkdtemp(prefix=".subforge-work-", dir=str(parent))).resolve()
    try:
        yield workspace
    finally:
        if not keep:
            # The exact, uniquely created child is the only permissible target.
            if workspace.parent != parent or not workspace.name.startswith(".subforge-work-"):
                raise RuntimeError("Pasta temporária fora do destino esperado; limpeza recusada.")
            shutil.rmtree(workspace, ignore_errors=True)


@contextmanager
def staged_output(final: Path):
    """Let external tools write a temporary file and publish only on success."""
    final = Path(final)
    fd, name = tempfile.mkstemp(prefix=".subforge-output-", suffix=final.suffix, dir=str(final.parent))
    os.close(fd)
    temporary = Path(name)
    try:
        yield temporary
        if temporary.stat().st_size == 0:
            raise ValueError("O processamento não produziu um arquivo válido.")
        if final.exists():
            raise FileExistsError(f"Destino já existe; resultado preservado: {final}")
        # Publish without clobbering a destination created after the check.
        if os.name == "nt":
            os.rename(temporary, final)
        else:
            os.link(temporary, final)
            temporary.unlink()
    finally:
        temporary.unlink(missing_ok=True)


def export_result(source: Path, preferred: Path) -> Path:
    """Publish a verified copy under an unused name, then remove the source.

    A failed copy/publication leaves the source and existing destinations intact.
    Selecting the current folder is a no-op, including filesystem aliases.
    """
    source, preferred = Path(source).resolve(), Path(preferred).resolve()
    if source == preferred or (preferred.exists() and os.path.samefile(source, preferred)):
        return source
    with reserve_output(preferred) as final:
        with staged_output(final) as temporary:
            shutil.copy2(source, temporary)
            # Do not remove the only complete copy after a short/interrupted copy.
            if temporary.stat().st_size != source.stat().st_size:
                raise OSError("A cópia do resultado ficou incompleta; a origem foi preservada.")
        source.unlink()
        return final
