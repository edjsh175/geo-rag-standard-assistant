"""Agent application core.

Import concrete Agent components from their owning modules. Keeping this package
initializer side-effect free prevents transport/retrieval contracts from
creating circular imports through convenience re-exports.
"""
