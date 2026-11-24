# Unmodified helper from J535D165/pyalex pyalex/api.py blob 7f8e8d4d5524698c2fa8ff4e25ff189aebc046f0; MIT, see api-vendor/PYALEX-LICENSE.txt.
def invert_abstract(inv_index):
    """Invert OpenAlex abstract index.

    Parameters
    ----------
    inv_index : dict
        Inverted index of the abstract.

    Returns
    -------
    str
        Inverted abstract.
    """
    if inv_index is not None:
        l_inv = [(w, p) for w, pos in inv_index.items() for p in pos]
        return " ".join(map(lambda x: x[0], sorted(l_inv, key=lambda x: x[1])))

