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


class CommonTests:
    """
    Tests for file names containing non-ASCII (e.g. cyrillic) symbols,
    mimicking output of various real-life ZIP archivers.

    This is an abstract class which has two implementations: one testing
    unzip and another one testing 7zip (see below).
    """

    filename = "абвгде"

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

        Test that with ru_RU.UTF-8 locale, the correct encoding is used by default,
        and that on other locales passing the encoding manually works.
        """

        zipinfo = custom_zip_info("cp866")(filename=self.filename)
        zipinfo.create_system = 0
        zipinfo.create_version = 20

        self._do_test(zipinfo, encoding="CP866")
        self._do_test(zipinfo, locale="ru_RU.UTF-8")

    def test_windows_encoding(self):
        """
        When create_system == 11 (Windows) and create_version >= 20, the
        filename field is treated as ANSI.

        Test that with ru_RU.UTF-8 locale, the correct encoding is used by default,
        and that on other locales passing the encoding manually works.
        """

        zipinfo = custom_zip_info("cp1251")(filename=self.filename)
        zipinfo.create_system = 11
        zipinfo.create_version = 30

        self._do_test(zipinfo, encoding="CP1251")
        self._do_test(zipinfo, locale="ru_RU.UTF-8")

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
        self._do_test(zipinfo, locale="ru_RU.UTF-8")

    def test_pkzip5(self):
        """
        PKZip version 5 and newer started using OEM encoding again. Let's test
        this configuration too.
        """

        zipinfo = custom_zip_info("cp866")(filename=self.filename)
        zipinfo.create_system = 0
        zipinfo.create_version = 50

        self._do_test(zipinfo, encoding="CP866")
        self._do_test(zipinfo, locale="ru_RU.UTF-8")


class UnzipTestCase(CommonTests, unittest.TestCase):
    def _do_test(self, zipinfo, encoding=None, locale=None):
        with tempfile.TemporaryFile(suffix=".zip") as fp:
            with zipfile.ZipFile(fp, "w") as zip_file:
                zip_file.writestr(zipinfo, b"")
            encoding_args = ["-I", encoding] if encoding else []
            args = ["zipinfo", "-1", *encoding_args, "/dev/stdin"]
            env = {"LC_CTYPE": locale} if locale else None
            output = subprocess.check_output(args, stdin=fp, env=env)

        self.assertEqual(output, f"{self.filename}\n".encode("utf-8"))


class SevenZipTestCase(CommonTests, unittest.TestCase):
    def _do_test(self, zipinfo, encoding=None, locale=None):
        with tempfile.TemporaryFile(suffix=".zip") as fp:
            with zipfile.ZipFile(fp, "w") as zip_file:
                zip_file.writestr(zipinfo, b"")
            encoding_args = []
            if encoding is not None:
                assert encoding.startswith("CP")
                encoding_args.append(f"-mcp={encoding[2:]}")
            args = ["7z", "l", "-slt", *encoding_args, "/dev/stdin"]
            env = {"LC_CTYPE": locale} if locale else None
            output = subprocess.check_output(args, stdin=fp, env=env)

        self.assertIn(f"Path = {self.filename}".encode("utf-8"), output.split(b"\n"))


class UnarTestCase(CommonTests, unittest.TestCase):
    def _do_test(self, zipinfo, encoding=None, locale=None):
        with tempfile.TemporaryFile(suffix=".zip") as fp:
            with zipfile.ZipFile(fp, "w") as zip_file:
                zip_file.writestr(zipinfo, b"")
            if encoding == "CP866":
                encoding_args = ["-e", "cp866"]
            elif encoding == "CP1251":
                encoding_args = ["-e", "windows-1251"]
            else:
                assert encoding is None
                encoding_args = []
            args = ["lsar", *encoding_args, "/dev/stdin"]
            env = {"LC_CTYPE": locale} if locale else None
            output = subprocess.check_output(args, stdin=fp, env=env)

        self.assertIn(self.filename.encode("utf-8"), output.split(b"\n"))

    @unittest.expectedFailure
    def test_windows_encoding(self):
        return super().test_windows_encoding()

    @unittest.expectedFailure
    def test_pkzip4(self):
        return super().test_pkzip4()


class BsdTarTestCase(CommonTests, unittest.TestCase):
    def _do_test(self, zipinfo, encoding=None, locale=None):
        if encoding is not None:
            return  # bsdtar does not support passing encoding

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zip_file:
            zip_file.writestr(zipinfo, b"")
        args = ["bsdtar", "-tf", "-"]
        env = {"LC_CTYPE": locale} if locale else None
        output = subprocess.check_output(args, input=buffer.getvalue(), env=env)

        self.assertEqual(output, f"{self.filename}\n".encode("utf-8"))

    @unittest.expectedFailure
    def test_dos_encoding(self):
        return super().test_dos_encoding()

    @unittest.expectedFailure
    def test_windows_encoding(self):
        return super().test_windows_encoding()

    @unittest.expectedFailure
    def test_pkzip4(self):
        return super().test_pkzip4()

    @unittest.expectedFailure
    def test_pkzip5(self):
        return super().test_pkzip5()


if __name__ == "__main__":
    unittest.main()
