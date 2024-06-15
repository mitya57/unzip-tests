#!/usr/bin/env python3

import binascii
import inspect
import io
import struct
import subprocess
import tempfile
import unittest
import zipfile


def custom_zip_info(local_encoding: str, central_encoding: str | None = None):
    """
    Wrapper around zipfile.ZipInfo that saves files with custom metadata
    encoding and no unicode flag.  Needed for mocking PKZip behavior.
    """

    if central_encoding is None:
        central_encoding = local_encoding

    class CustomEncodingZipInfo(zipfile.ZipInfo):
        def _encodeFilenameFlags(self):
            if inspect.stack()[1][3] == "_write_end_record":
                encoding = central_encoding
            else:
                encoding = local_encoding
            return self.filename.encode(encoding), self.flag_bits

    return CustomEncodingZipInfo


class UnicodeNamesTestCases(unittest.TestCase):
    """
    Tests for file names containing non-ASCII (e.g. cyrillic) symbols,
    mimicking output of various real-life ZIP archivers.
    """

    filename = "абвгде"

    def _do_test(self, zipinfo, encoding=None):
        with tempfile.TemporaryFile(suffix=".zip") as fp:
            with zipfile.ZipFile(fp, "w") as zip_file:
                zip_file.writestr(zipinfo, b"")
            encoding_args = ["-I", encoding] if encoding else []
            args = ["zipinfo", "-1", *encoding_args, "/dev/stdin"]
            output = subprocess.check_output(args, stdin=fp)

        self.assertEqual(output, f"{self.filename}\n".encode("utf-8"))

    def test_unicode_field(self):
        """
        When Info-ZIP Unicode Path Extra Field (0x7075) is present, it should
        be used instead of the normal filename header.
        """

        zipinfo = zipfile.ZipInfo(filename="ignore")
        zipinfo.create_system = 0

        filename_encoded = struct.pack("<BL", 1, binascii.crc32(b"ignore"))
        filename_encoded += self.filename.encode("utf-8")
        zipinfo.extra = struct.pack("<HH", 0x7075, len(filename_encoded))
        zipinfo.extra += filename_encoded

        self._do_test(zipinfo)

    def test_bit11(self):
        """
        When general purpose bit 11 is set (Python does this by default),
        the filename field is treated as UTF-8.
        """

        zipinfo = zipfile.ZipInfo(filename=self.filename)
        zipinfo.create_system = 0

        self._do_test(zipinfo)

    def test_dos_encoding(self):
        """
        When create_system == 0 (MS-DOS), the filename field is treated as OEM.

        We cannot set locale in the test (e.g. to ru_RU.UTF-8) because it is
        not necessarily registered, so let's at least test passing the locale
        manually.
        """

        zipinfo = custom_zip_info("cp866")(filename=self.filename)
        zipinfo.create_system = 0
        zipinfo.create_version = 20

        self._do_test(zipinfo, encoding="CP866")

    def test_windows_encoding(self):
        """
        When create_system == 11 (Windows) and create_version >= 20, the
        filename field is treated as ANSI.

        We cannot set locale in the test (e.g. to ru_RU.UTF-8) because it is
        not necessarily registered, so let's at least test passing the locale
        manually.
        """

        zipinfo = custom_zip_info("cp1251")(filename=self.filename)
        zipinfo.create_system = 11
        zipinfo.create_version = 30

        self._do_test(zipinfo, encoding="CP1251")

    def test_unix_encoding(self):
        """
        When create_system == 3 (UNIX), the filename field is treated as UTF-8.
        """

        zipinfo = custom_zip_info("utf-8")(filename=self.filename)
        zipinfo.create_system = 3

        self._do_test(zipinfo)

    def test_pkzip4(self):
        """
        If central header and local header have different encodings, e.g.
        central OEM and local ANSI, the encoding from central header is used.

        Such files were generated by PKZip for Windows 2.5, 2.6, and 4.0.
        """

        zipinfo = custom_zip_info("cp1251", "cp866")(filename=self.filename)
        zipinfo.create_system = 0
        zipinfo.create_version = 40

        # Make sure both encodings are really present in the generated file.
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zip_file:
            zip_file.writestr(zipinfo, b"")
        self.assertIn(self.filename.encode("cp1251"), buffer.getvalue())
        self.assertIn(self.filename.encode("cp866"), buffer.getvalue())

        self._do_test(zipinfo, encoding="CP866")

    def test_pkzip5(self):
        """
        PKZip version 5 and newer started using OEM encoding again. Let's test
        this configuration too.
        """

        zipinfo = custom_zip_info("cp866")(filename=self.filename)
        zipinfo.create_system = 0
        zipinfo.create_version = 50

        self._do_test(zipinfo, encoding="CP866")


if __name__ == "__main__":
    unittest.main()
