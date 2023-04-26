.. image:: https://github.com/con/tinuous/workflows/Test/badge.svg?branch=master
    :target: https://github.com/con/tinuous/actions?workflow=Test
    :alt: GitHub Actions Status

.. image:: https://travis-ci.com/con/tinuous.svg?branch=master
    :target: https://travis-ci.com/con/tinuous
    :alt: Travis CI Status

.. image:: https://ci.appveyor.com/api/projects/status/github/con/tinuous?branch=master&svg=true
    :target: https://ci.appveyor.com/project/yarikoptic/tinuous/branch/master
    :alt: Appveyor Status

.. image:: https://dl.circleci.com/status-badge/img/gh/con/tinuous/tree/master.svg?style=svg
    :target: https://dl.circleci.com/status-badge/redirect/gh/con/tinuous/tree/master
    :alt: CircleCI Status

.. image:: https://img.shields.io/pypi/pyversions/tinuous.svg
    :target: https://pypi.org/project/tinuous/

.. image:: https://img.shields.io/conda/vn/conda-forge/tinuous.svg
    :target: https://anaconda.org/conda-forge/tinuous
    :alt: Conda Version

.. image:: https://img.shields.io/github/license/con/tinuous.svg
    :target: https://opensource.org/licenses/MIT
    :alt: MIT License

`GitHub <https://github.com/con/tinuous>`_
| `PyPI <https://pypi.org/project/tinuous/>`_
| `Anaconda <https://anaconda.org/conda-forge/tinuous>`_
| `Issues <https://github.com/con/tinuous/issues>`_
| `Changelog <https://github.com/con/tinuous/blob/master/CHANGELOG.md>`_

``tinuous`` is a command for downloading build logs, artifacts, & release
assets for a GitHub repository from GitHub Actions, Travis-CI.com, Appveyor,
and/or CircleCI.

See <https://github.com/con/tinuous-inception> for an example setup that uses
``tinuous`` with GitHub Actions to fetch the CI logs for ``tinuous`` itself.

Installation
============
``tinuous`` requires Python 3.8 or higher.  Just use `pip
<https://pip.pypa.io>`_ for Python 3 (You have pip, right?) to install
``tinuous`` and its dependencies::

    python3 -m pip install tinuous

``tinuous`` can also optionally integrate with DataLad_.  To install DataLad
alongside ``tinuous``, specify the ``datalad`` extra::

    python3 -m pip install "tinuous[datalad]"

``tinuous`` is also available for conda!  To install, run::

    conda install -c conda-forge tinuous


Usage
=====

::

    tinuous [<global options>] <command> [<args> ...]


Global Options
--------------

-c FILE, --config FILE          Read configuration from the given file [default
                                value: ``tinuous.yaml``]

-E FILE, --env FILE             Load environment variables from the given
                                ``.env`` file.  By default, environment
                                variables are loaded from the first file named
                                "``.env``" found by searching from the current
                                directory upwards.

                                **Warning**: Care must be taken when this file
                                is located in a Git repository so as not to
                                publicly expose it: either list the file in
                                ``.gitignore`` or, if using DataLad or
                                git-annex, configure git-annex to prohibit
                                public sharing of the file.

-l LEVEL, --log-level LEVEL     Set the log level to the given value.  Possible
                                values are "``CRITICAL``", "``ERROR``",
                                "``WARNING``", "``INFO``", "``DEBUG``" (all
                                case-insensitive) and their Python integer
                                equivalents.  [default value: INFO]


``fetch`` Command
-----------------

::

    tinuous [<global options>] fetch [<options>]

``tinuous fetch`` reads a configuration file telling it what repository to
retrieve logs & artifacts for, where to retrieve them from, and where to save
them, and then it carries those steps out.

Options
~~~~~~~

--sanitize-secrets              Sanitize secrets from log files after
                                downloading

-S FILE, --state FILE           Store program state (e.g., timestamps before
                                which all asset are known to have been fetched)
                                in the given file [default value:
                                ``.tinuous.state.json``]

``sanitize`` Command
--------------------

::

    tinuous [<global options>] sanitize <path> ...

Sanitize the given files, replacing all strings matching a secret regex with a
series of asterisks.


Configuration
-------------

The configuration file is a YAML file containing a mapping with the following
keys:

``repo``
    *(required)* The GitHub repository to retrieve assets for, in the form ``OWNER/NAME``

``vars``
    A mapping defining custom path template placeholders.  Each key is the name
    of a custom placeholder, without enclosing braces, and the value is the
    string to substitute in its place.  Custom values may contain standard path
    template placeholders as well as other custom placeholders.

``ci``
    *(required)* A mapping from the names of the CI systems from which to
    retrieve assets to sub-mappings containing CI-specific configuration.
    Including a given CI system is optional; assets will only be fetched from a
    given system if it is listed in this mapping.

    The CI systems and their sub-mappings are as follows:

    ``github``
        Configuration for retrieving assets from GitHub Actions.  Subfields:

        ``paths``
            A mapping giving `template strings <Path Templates_>`_ for the
            paths at which to save various types of assets.  If this is empty
            or not present, no assets are retrieved.  Subfields:

            ``logs``
                A template string that will be instantiated for each workflow
                run to produce the path for the directory (relative to the
                current working directory) under which the run's build logs
                will be saved.  If this is not specified, no logs will be
                downloaded.

            ``artifacts``
                A template string that will be instantiated for each workflow
                run to produce the path for the directory (relative to the
                current working directory) under which the run's artifacts will
                be saved.  If this is not specified, no artifacts will be
                downloaded.

            ``releases``
                A template string that will be instantiated for each
                (non-draft, non-prerelease) GitHub release to produce the path
                for the directory (relative to the current working directory)
                under which the release's assets will be saved.  If this is not
                specified, no release assets will be downloaded.

        ``workflows``
            A specification of the workflows for which to retrieve assets.
            This can be either a list of workflow basenames, including the file
            extension (e.g., ``test.yml``, not ``.github/workflows/test.yml``)
            or a mapping containing the following fields:

            ``include``
                A list of workflows to retrieve assets for, given as either
                basenames or (when ``regex`` is true) `Python regular
                expressions`_ to match against basenames.  If ``include`` is
                omitted, it defaults to including all workflows.

            ``exclude``
                A list of workflows to not retrieve assets for, given as either
                basenames or (when ``regex`` is true) `Python regular
                expressions`_ to match against basenames.  If ``exclude`` is
                omitted, no workflows are excluded.  Workflows that match both
                ``include`` and ``exclude`` are excluded.

            ``regex``
                A boolean.  If true (default false), the elements of the
                ``include`` and ``exclude`` fields are treated as `Python
                regular expressions`_ that are matched (unanchored) against
                workflow basenames; if false, they are used as exact names

            When ``workflows`` is not specified, assets are retrieved for all
            workflows in the repository.

    ``travis``
        Configuration for retrieving logs from Travis-CI.com.  Subfield:

        ``paths``
            A mapping giving `template strings <Path Templates_>`_ for the
            paths at which to save various types of assets.  If this is empty
            or not present, no assets are retrieved.  Subfield:

            ``logs``
                A template string that will be instantiated for each job of
                each build to produce the path for the file (relative to the
                current working directory) in which the job's logs will be
                saved.  If this is not specified, no logs will be downloaded.

    ``appveyor``
        Configuration for retrieving logs from Appveyor.  Subfields:

        ``paths``
            A mapping giving `template strings <Path Templates_>`_ for the
            paths at which to save various types of assets.  If this is empty
            or not present, no assets are retrieved.  Subfield:

            ``logs``
                A template string that will be instantiated for each job of
                each build to produce the path for the file (relative to the
                current working directory) in which the job's logs will be
                saved.  If this is not specified, no logs will be downloaded.

        ``accountName``
            *(required)* The name of the Appveyor account to which the
            repository belongs on Appveyor

        ``projectSlug``
            The project slug for the repository on Appveyor; if not specified,
            it is assumed that the slug is the same as the repository name

    ``circleci``
        Configuration for retrieving assets from CircleCI.  Subfields:

        ``paths``
            A mapping giving `template strings <Path Templates_>`_ for the
            paths at which to save various types of assets.  If this is empty
            or not present, no assets are retrieved.  Subfields:

            ``logs``
                A template string that will be instantiated for each action of
                each step of each job of each workflow of each pipeline to
                produce the path for the file (relative to the current working
                directory) under which the actions's build logs will be saved.
                If this is not specified, no logs will be downloaded.

            ``artifacts``
                A template string that will be instantiated for each job to
                produce the path for the directory (relative to the current
                working directory) under which the job's artifacts will be
                saved.  If this is not specified, no artifacts will be
                downloaded.

``since``
    A timestamp (date, time, & timezone); only assets for builds started after
    the given point in time will be retrieved.  If not specified, the cutoff
    set by ``max-days-back`` will be used.

    As the script retrieves new build assets, it keeps track of their starting
    points.  Once the assets for all builds for the given CI system &
    configuration have been fetched up to a certain point, the timestamp for
    the latest such build is stored in the state file and used as the new
    ``since`` value for the respective CI system on subsequent runs.  If the
    ``since`` setting in the configuration file is then updated to a newer
    timestamp, the configuration will override the value in the state file, and
    the next ``tinuous`` run will only retrieve assets after the new setting.

``max-days-back``
    An integer specifying the maximum number of days back to look for builds;
    defaults to 30.

    If ``since`` is earlier than the date indicated by this value, and if the
    timestamp for a given CI system saved in the state file is either missing
    (i.e., if this is the first run of ``tinuous`` against the CI system) or
    older than ``since``, then ``tinuous`` will use the explicitly-specified
    ``since`` value as the cutoff and ignore ``max-days-back``.

``until``
    A timestamp (date, time, & timezone); only assets for builds started before
    the given point in time will be retrieved

``types``
    A list of build trigger event types; only assets for builds triggered by
    one of the given events will be retrieved.  If this is not specified,
    assets will be retrieved for all recognized event types.

    The recognized event types are:

    ``cron``
        A build run on a schedule

    ``manual``
        A build triggered manually by a human or through the CI system's API

    ``pr``
        A build in response to activity on a pull request

    ``push``
        A build in response to new commits

``secrets``
    A mapping from names (used in log messages) to `Python regular
    expressions`_ matching secrets to sanitize

``allow-secrets-regex``
    Any strings that match a ``secrets`` regex and also match this regex will
    not be sanitized.  Note that ``allow-secrets-regex`` is tested against just
    the substring that matched a ``secrets`` regex without any surrounding
    text, and so lookahead and lookbehind will not work in this regex.

``datalad``
    A sub-mapping describing integration of ``tinuous`` with DataLad_.
    Subfields:

    ``enabled``
        A boolean.  If true (default false), DataLad must be installed, the
        current directory will be converted into a DataLad dataset if it is not
        one already, the assets will optionally be divided up into subdatasets,
        and all new assets will be committed at the end of a run of ``tinuous
        fetch``.  ``path`` template strings may contain ``//`` separators
        indicating the boundaries of subdatasets.

    ``cfg_proc``
        Procedure to run on the dataset & subdatasets when creating them

    .. _DataLad: https://www.datalad.org

.. _Python regular expressions: https://docs.python.org/3/library/re.html
                                #regular-expression-syntax

A sample config file:

.. code:: yaml

    repo: datalad/datalad
    vars:
      path_prefix: '{year}//{month}//{day}/{ci}/{type}'
      build_prefix: '{path_prefix}/{type_id}/{build_commit[:7]}'
    ci:
      github:
        paths:
          logs: '{build_prefix}/{wf_name}/{number}/logs/'
          artifacts: '{build_prefix}/{wf_name}/{number}/artifacts/'
          releases: '{path_prefix}/{release_tag}/'
        workflows:
          - test_crippled.yml
          - test_extensions.yml
          - test_macos.yml
      travis:
        paths:
          logs: '{build_prefix}/{number}/{job}.txt'
      appveyor:
        paths:
          logs: '{build_prefix}/{number}/{job}.txt'
        accountName: mih
        projectSlug: datalad
      circleci:
        paths:
          logs: '{build_prefix}/{wf_name}/{number}/{job_name}/{step}-{index}.txt'
          artifacts: '{path_prefix}/{wf_name}/{number}/{job_name}/artifacts/'
    since: 2021-01-20T00:00:00Z
    max-days-back: 14
    types: [cron, manual, pr, push]
    secrets:
      github: '\bgh[a-z]_[A-Za-z0-9]{36,}\b'
      docker-hub: '\b[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\b'
      appveyor: '\b(v2\.)?[a-z0-9]{20}\b'
      travis: '\b[a-zA-Z0-9]{22}\b'
      aws: '\b[a-zA-Z0-9+/]{40}\b'
    datalad:
      enabled: true
      cfg_proc: text2git


Path Templates
--------------

The path at which assets for a given workflow run, build job, or release are
saved is determined by instantiating the appropriate path template string given
in the configuration file for the corresponding CI system.  A template string
is a filepath containing placeholders of the form ``{field}``, where the
available placeholders are:

======================  =======================================================
Placeholder             Definition
======================  =======================================================
``{year}``              The four-digit year in which the build was started or
                        the release was published
``{month}``             The two-digit month in which the build was started or
                        the release was published
``{day}``               The two-digit day in which the build was started or the
                        release was published
``{hour}``              The two-digit hour at which the build was started or
                        the release was published
``{minute}``            The two-digit minute at which the build was started or
                        the release was published
``{second}``            The two-digit second at which the build was started or
                        the release was published
``{timestamp}``         The date & time at which the build was started or the
                        release was published.  This is a Python datetime_
                        value; it can be formatted with a `strftime()`_ format
                        string by writing ``{timestamp:FORMAT}``, e.g.,
                        ``{timestamp:%Y-%b-%d}`` will produce a string of the
                        form "2021-Jun-14".  If written as just
                        ``{timestamp}``, the date & time will be formatted in
                        ISO 8601 format.
``{timestamp_local}``   The date & time at which the build was started or the
                        release was published, in the local system timezone.
                        This is formatted in the same way as ``{timestamp}``.
``{ci}``                The name of the CI system (``github``, ``travis``,
                        ``appveyor``, or ``circleci``)
``{type}``              The event type that triggered the build (``cron``,
                        ``manual``, ``pr``, or ``push``), or ``release`` for
                        GitHub releases
``{type_id}``           Further information on the triggering event; for
                        ``cron`` and ``manual``, this is a timestamp for the
                        start of the build; for ``pr``, this is the number of
                        the associated pull request, or ``UNK`` if it cannot be
                        determined; for ``push``, this is the escaped [1]_ name
                        of the branch to which the push was made (or possibly
                        the tag that was pushed, if using Appveyor or CircleCi)
                        [2]_
``{release_tag}``       *(``releases_path`` only)* The release tag
``{build_commit}``      The hash of the commit the build ran against or that
                        was tagged for the release.  Note that, for PR builds
                        on Travis and Appveyor, this is the hash of an
                        autogenerated merge commit.
``{commit}``            The hash of the original commit that triggered the
                        build or that was tagged for the release.  For pull
                        request builds, this is the head of the PR branch, or
                        ``UNK`` if it cannot be determined.  For other builds
                        (along with PR builds on GitHub Actions), this is
                        always the same as ``{build_commit}``.
``{number}``            The run number of the workflow run (GitHub) or the
                        build number (Travis and Appveyor) or the pipeline
                        number (CircleCI) [2]_
``{status}``            The success status of the workflow run (GitHub) or job
                        (Travis and Appveyor) or action (CircleCI); the exact
                        strings used depend on the CI system [2]_
``{common_status}``     The success status of the workflow run, job, or action,
                        normalized into one of ``success``, ``failed``,
                        ``errored``, or ``incomplete`` [2]_
``{wf_name}``           *(GitHub and CircleCI only)* The escaped [1]_ name of
                        the workflow [2]_
``{wf_file}``           *(GitHub only)* The basename of the workflow file
                        (including the file extension) [2]_
``{wf_id}``             *(CircleCI only)* The UUID of the workflow [2]_
``{run_id}``            *(GitHub only)* The unique ID of the workflow run [2]_
``{pipeline_id}``       *(CircleCI only)* The UUID of the pipeline [2]_
``{job}``               *(Travis, Appveyor, and CircleCI only)* The number of
                        the job, without the build number prefix (Travis) or
                        the job ID string (Appveyor) [2]_
``{job_index}``         *(Travis and Appveyor only)* The index of the job in
                        the list returned by the API, starting from 1 [2]_
``{job_env}``           *(Appveyor only)* The escaped [1]_ environment
                        variables specific to the job [2]_
``{job_env_hash}``      *(Appveyor only)* The SHA1 hash of ``{job_env}`` before
                        escaping [2]_
``{job_id}``            *(CircleCI only)* The UUID of the job [2]_
``{job_name}``          *(CircleCI only)* The escaped [1]_ name of the job [2]_
``{step}``              *(CircleCI only)* The number of the step [2]_
``{step_name}``         *(CircleCI only)* The escaped [1]_ name of the step [2]_
``{index}``             *(CircleCI only)* The index of the parallel container
                        that the step ran on [2]_
======================  =======================================================

.. _datetime: https://docs.python.org/3/library/datetime.html#datetime-objects
.. _strftime(): https://docs.python.org/3/library/datetime.html
                #strftime-and-strptime-format-codes

.. [1] Escaping consists of percent-encoding the characters ``\/<>:|"?*%`` and
       replacing each whitespace character with a space.

.. [2] These placeholders are only available for ``path`` and
       ``artifacts_path``, not ``releases_path``

A placeholder's value may be truncated to the first ``n`` characters by writing
``{placeholder[:n]}``, e.g., ``{commit[:7]}``.

All timestamps and timestamp components (other than ``{timestamp_local}``) are
in UTC.

Path templates may also contain custom placeholders defined in the top-level
``vars`` mapping of the configuration.

Authentication
--------------

Note that environment variables can be loaded from a ``.env`` file as an
alternative to setting them directly in the environment.

GitHub
~~~~~~

In order to retrieve assets from GitHub, a GitHub OAuth token must be specified
either via the ``GITHUB_TOKEN`` environment variable or as the value of the
``hub.oauthtoken`` Git config option.

Travis
~~~~~~

In order to retrieve logs from Travis, a Travis API access token must be either
specified via the ``TRAVIS_TOKEN`` environment variable or be retrievable by
running ``travis token --com --no-interactive``.

A Travis API access token can be acquired as follows:

- Install the `Travis command line client
  <https://github.com/travis-ci/travis.rb>`_.

- Run ``travis login --com`` to authenticate.

  - If your Travis account is linked to your GitHub account, you can
    authenticate by running ``travis login --com --github-token
    $GITHUB_TOKEN``.

- If ``tinuous`` will be run on the same machine that the above steps are
  carried out on, you can stop here, and ``tinuous`` will retrieve the token
  directly from the ``travis`` command.

- Run ``travis token --com`` to retrieve the API access token.

The Travis integration also requires a GitHub OAuth token in order to look up
information on pull requests that the Travis API does not report; this token
must be specified in the same way as for the GitHub integration.

Appveyor
~~~~~~~~

In order to retrieve logs from Appveyor, an Appveyor API key (for either all
accessible accounts or just the specific account associated with the
repository) must be specified via the ``APPVEYOR_TOKEN`` environment variable.
Such a key can be obtained at <https://ci.appveyor.com/api-keys>.

CircleCI
~~~~~~~~

In order to retrieve logs & artifacts from CircleCi, a CircleCI API token
(either a personal token or a project token with at least read access) must be
specified via the ``CIRCLECI_CLI_TOKEN`` environment variable.

Alternatively, if you have installed the `CircleCI local CLI
<https://circleci.com/docs/local-cli/>`_ on the same machine that ``tinuous``
will be running on and supplied an API token to it by running ``circleci
setup``, ``tinuous`` will read the supplied API token from the CLI's config
file.

See <https://circleci.com/docs/managing-api-tokens/> for instructions on how to
obtain a CircleCI API token.


Cron Integration
================

If you want to set up scheduled runs of ``tinuous`` on a Linux server, one way
is as follows:

1. Create a new directory and ``cd`` into it.

2. Create a file named ``tinuous.yaml`` in this directory `as described above
   <Configuration_>`_

3. Create a file named ``.env`` in this directory containing any needed
   authentication tokens.  Entries are of the form ``NAME=value``, e.g.::

        GITHUB_TOKEN=ghp_abcdef0123456789
        TRAVIS_TOKEN=asdfghjkl
        APPVEYOR_TOKEN=v2.qwertyuiop
        CIRCLECI_CLI_TOKEN=zxcvbnm

4. Create a Python virtualenv_ to provide an isolated environment to install
   ``tinuous`` into::

        python3 -m venv venv

5. Install ``tinuous`` inside the virtualenv::

        venv/bin/pip install tinuous

   If you want to use DataLad with ``tinuous``, you need to install it as well,
   even if it's already installed outside the virtualenv::

        venv/bin/pip install datalad

6. Run ``tinuous`` to fetch your first logs and test your configuration::

        venv/bin/tinuous fetch

7. Once you're satisfied with your ``tinuous`` config, set up scheduled runs by
   creating a cronjob of the form::

        0 0 * * * cd /path/to/directory && chronic flock -n -E 0 .tinuous.lock venv/bin/tinuous fetch

   This job runs once a day at midnight; adjust the cron expression to taste.
   We use ``chronic`` (from moreutils_) to suppress output unless the command
   fails, thus preventing e-mails full of log messages for every run.
   ``flock`` is used to ensure that no more than one instance of ``tinuous`` is
   running at a time.

8. If you want to commit your logs to a Git repository, first make sure that
   ``.env``, ``venv/``, and ``.tinuous.lock`` are included in the repository's
   ``.gitignore``.  Consider setting up the repository with DataLad_; when the
   DataLad integration is enabled, ``tinuous`` will automatically commit any
   new logs at the end of a run.

   If you're using a regular Git repository instead, you can commit any new
   logs at the end of a run by adding the following script to your ``tinuous``
   directory:

   .. code:: bash

       #!/bin/bash
       set -ex
       venv/bin/tinuous fetch
       git add --all
       if ! git diff --cached --quiet
       then git commit -m "Ran tinuous"
            # Uncomment if you want to push the commits to a remote repository:
            #git push
       fi

   and changing your cronjob to::

        0 0 * * * cd /path/to/directory && chronic flock -n -E 0 .tinuous.lock bash name-of-script.sh

9. If you ever need to upgrade ``tinuous``, run the following command inside
   your ``tinuous`` directory::

        venv/bin/pip install --upgrade tinuous

10. Enjoy your collection of logs, build artifacts, and/or release assets!

.. _virtualenv: https://packaging.python.org/guides/installing-using-pip-and
                -virtual-environments/

.. _moreutils: https://joeyh.name/code/moreutils/
