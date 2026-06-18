class _Deleted:
    """Sentinel marking a key removed within a transaction layer."""
    __slots__ = ()


_DELETED = _Deleted()


class KVStore:
    def __init__(self):
        self._base = {}          # committed store: key -> value
        self._stack = []         # open transactions, each a dict key -> value | _DELETED

    # --- reads ---
    def get(self, key):
        for layer in reversed(self._stack):
            if key in layer:
                v = layer[key]
                return None if v is _DELETED else v
        return self._base.get(key)

    def _visible(self):
        result = dict(self._base)
        for layer in self._stack:
            for k, v in layer.items():
                if v is _DELETED:
                    result.pop(k, None)
                else:
                    result[k] = v
        return result

    def keys(self):
        return sorted(self._visible())

    def __len__(self):
        return len(self._visible())

    # --- writes ---
    def set(self, key, value):
        if self._stack:
            self._stack[-1][key] = value
        else:
            self._base[key] = value

    def delete(self, key):
        if self._stack:
            self._stack[-1][key] = _DELETED
        else:
            self._base.pop(key, None)

    # --- transactions ---
    def begin(self):
        self._stack.append({})

    def commit(self):
        if not self._stack:
            raise RuntimeError("no open transaction")
        layer = self._stack.pop()
        if self._stack:
            parent = self._stack[-1]
            parent.update(layer)            # carry sets and _DELETED markers up
        else:
            for k, v in layer.items():
                if v is _DELETED:
                    self._base.pop(k, None)
                else:
                    self._base[k] = v

    def rollback(self):
        if not self._stack:
            raise RuntimeError("no open transaction")
        self._stack.pop()
