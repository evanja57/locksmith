Developer Guide
===============

Environment
-----------

The current package metadata requires Python ``>=3.14.0``. Use Python ``3.14``
for local development and documentation work so dependency resolution matches CI
and release builds.

Setup
-----

From the repository root:

.. code-block:: bash

   python3.14 -m venv .venv
   source .venv/bin/activate
   python -m pip install --upgrade pip
   python -m pip install -e .

Qt Resource Regeneration
------------------------

The generated Qt resource module lives at ``src/locksmith/resources_rc.py``.

.. code-block:: bash

   python ./scripts/generate_qrc.py
   pyside6-rcc resources.qrc -o resources_rc.py
   mv resources_rc.py ./src/locksmith/

Running Locksmith
-----------------

Once the editable install is in place:

.. code-block:: bash

   python -m locksmith.main

Building The Docs
-----------------

This repo now has a narrow Sphinx scaffold for developer-oriented documentation. Additional
topic guides can be layered onto that scaffold without changing the local docs workflow.

.. code-block:: bash

   python -m pip install -r docs/requirements.txt
   sphinx-build -b html docs docs/_build/html

Plugin Lifecycle
----------------

The first plugin touchpoint happens when ``LocksmithWindow`` creates
``LocksmithApplication`` and calls ``PluginManager.discover_and_initialize(...)``.

Each plugin is:

#. discovered from the ``locksmith.plugins`` entry-point group
#. instantiated with no constructor arguments
#. initialized once with the application object
#. asked to register its pages and navigation menu section

Later, when a vault opens, the application calls ``PluginManager.on_vault_opened(vault)``.
That callback lets a plugin bind to vault-local state and return background doers that are
added to ``vault.doers``.

When a vault closes, ``PluginManager.on_vault_closed(vault)`` gives plugins a teardown hook
before the application closes LMDB-backed resources.
