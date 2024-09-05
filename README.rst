.. image:: https://img.shields.io/pypi/v/webrtcvad-wheels.svg
    :target: https://pypi.python.org/pypi/webrtcvad-wheels/
    :alt: PyPI Version
.. image:: https://img.shields.io/pypi/pyversions/webrtcvad-wheels.svg
    :target: https://pypi.python.org/pypi/webrtcvad-wheels/
    :alt: Supported Python Versions
.. image:: https://img.shields.io/pypi/wheel/webrtcvad-wheels.svg
    :target: https://pypi.python.org/pypi/webrtcvad-wheels/
    :alt: Wheel Support
.. image:: https://img.shields.io/pypi/dm/webrtcvad-wheels.svg?logo=python
    :target: https://pypi.python.org/pypi/webrtcvad-wheels/
    :alt: Downloads per Month
.. image:: https://github.com/daanzu/py-webrtcvad-wheels/actions/workflows/build.yml/badge.svg
    :target: https://github.com/daanzu/py-webrtcvad-wheels/actions/workflows/build.yml
    :alt: Build Status
.. image:: https://img.shields.io/badge/donate-PayPal-green.svg
    :target: https://paypal.me/daanzu
    :alt: Donate via PayPal
.. image:: https://img.shields.io/badge/sponsor-GitHub-pink.svg
    :target: https://github.com/sponsors/daanzu
    :alt: Sponsor on GitHub

py-webrtcvad-wheels
===================

This is a python interface to the WebRTC Voice Activity Detector (VAD).
It is forked from
`wiseman/py-webrtcvad <https://github.com/wiseman/py-webrtcvad>`_ to
provide updated releases with **binary wheels for Windows, macOS, and
Linux**. Also includes **additional fixes and improvements**.

A `VAD <https://en.wikipedia.org/wiki/Voice_activity_detection>`_
classifies a piece of audio data as being voiced or unvoiced. It can
be useful for telephony and speech recognition.

The VAD that Google developed for the `WebRTC <https://webrtc.org/>`_
project is reportedly one of the best available, being fast, modern
and free.

How to use it
-------------

0. Install the webrtcvad module::

    pip install webrtcvad-wheels

1. Create a ``Vad`` object::

    import webrtcvad
    vad = webrtcvad.Vad()

2. Optionally, set its aggressiveness mode, which is an integer
   between 0 and 3 (inclusive). 0 is the least aggressive about filtering out
   non-speech, 3 is the most aggressive. (You can also set the mode
   when you create the VAD, e.g. ``vad = webrtcvad.Vad(3)``; the default is ``0``)::

    vad.set_mode(1)

3. Give it a short segment ("frame") of audio. The WebRTC VAD only
   accepts 16-bit mono PCM audio, sampled at 8000, 16000, 32000 or 48000 Hz.
   A frame must be either 10, 20, or 30 ms in duration::

    # Run the VAD on 10 ms of silence. The result should be False.
    sample_rate = 16000
    frame_duration = 10  # ms
    frame = b'\x00\x00' * int(sample_rate * frame_duration / 1000)
    print 'Contains speech: %s' % (vad.is_speech(frame, sample_rate)


See `example.py
<https://github.com/daanzu/py-webrtcvad-wheels/blob/master/example.py>`_ for
a more detailed example that will process a .wav file, find the voiced
segments, and write each one as a separate .wav.


How to run unit tests
---------------------

To run unit tests::

    pip install -e ".[dev]"
    python setup.py test


History
-------

2.0.14

* Add RISC-V support (but no wheels yet). Thanks, `hack3ric <https://github.com/hack3ric>`_!
* Add loongarch64 support (but no wheels yet). Thanks, `zhangwenlong8911 <https://github.com/zhangwenlong8911>`_!

2.0.13

* Add tests for memory leaks.
* Fix memory leak in constructing `Vad` objects. Thanks, `manipopopo <https://github.com/manipopopo>`_!

2.0.12

* Add Python 3.12 & 3.13 builds.
* Fix `pkg_resources` usage for Python 3.12+.

2.0.11.post1

* Force build of new wheels.

2.0.11

* Fix out-of-bounds memory read in WebRtcVad_FindMinimum.
* Add Python 3.10 & 3.11 builds.
* Add PPC support & builds.
* Implement CI/CD with GitHub Actions instead.

2.0.10.post2

* Revert updating to the latest webrtcvad upstream version, as it breaks build.
* Tweak CI/CD configuration.
* Add Python 3.9 build.

2.0.10.post1

* Merge various changes from upstream.
* Implement CI/CD with Travis CI.

FORK

2.0.10

* Fixed memory leak. Thank you, `bond005 <https://github.com/bond005>`_!

2.0.9

* Improved example code. Added WebRTC license.

2.0.8

* Fixed Windows compilation errors. Thank you, `xiongyihui <https://github.com/xiongyihui>`_!
