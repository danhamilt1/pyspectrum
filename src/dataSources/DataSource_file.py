"""
File input class

"""
import time
from typing import Tuple
import wave
import logging

import numpy as np

from dataSources import DataSource

logger = logging.getLogger('spectrum_logger')

module_type = "file"
help_string = f"{module_type}:Filename \t- Filename, binary or wave, e.g. " \
              f"{module_type}:./xyz.cf123.4.cplx.200000.16tbe"


# return an error string if we are not available
def is_available() -> Tuple[str, str]:
    return module_type, ""


def parse_filename(filename: str) -> Tuple[bool, str, bool, float, float]:
    """
    Parse an filename to extract its information

    Filename should end in .cplx.sample_rate.sample_type
    sometimes there is a centre frequency part as well, cf in MHz
    e.g
    xyz.cf1234.45.cplx.10000.16tle - little endian
    xyz.cf1234.01.real.10000.16tbe - real and big endian - not supported due to being real
    xyz.cf1234.23.cplx.10000.8be
    xyz.cf1234.cplx.10000.8be     - no digits after decimal point


    :param filename:
    :return: A tuple with an ok flag, and the type [8t,16tbe,16tle...], complex flag and sample rate in Hz
    """
    data_type: str = ""
    complex_flag: bool = True
    sample_rate_hz = 0.0
    centre_frequency = 0.0
    ok: bool = False

    if filename:
        parts = [x.strip() for x in filename.split('.')]
        # work from end
        if len(parts) >= 4:
            # test.cf1234.0.cplx.1000.16tle -> ['test', 'cf1234', '0', 'cplx', '1000', '16tle']
            # test.cf1234.cplx.1000.16tle -> ['test', 'cf1234', 'cplx', '1000', '16tle']
            # test.cplx.1000.16tle -> ['test', 'cplx', '1000', '16tle']
            data_type = parts[-1]
            sample_rate = parts[-2]
            cplx = parts[-3]

            # cf parse is quite complex, first off is '.cf' in the filename
            if ".cf" in filename:
                indices = [i for i, part in enumerate(parts) if 'cf' in part]
                # if we find more than one .cf index then all bets are off
                if len(indices) == 1:
                    index = indices[0]  # where the .cf is in the list of parts
                    try:
                        cf = parts[index]
                        # is the next index real/cplx
                        if parts[index + 1] in ["cplx", "real"]:
                            # short cf with no decimal point
                            # ['test', '?', '?', ..., 'cf1234', 'cplx', '1000', '16tle']
                            # drop the 'cf'
                            centre_frequency = float(cf[2:]) * 1e6
                        else:
                            # long cf with a decimal point
                            #  ['test', '?', '?', ..., 'cf1234', '0', 'cplx', '1000', '16tle']
                            cf_decimal_fraction = parts[-4]
                            # drop the 'cf' and add in the decimal fraction part
                            cf = cf[2:] + "." + cf_decimal_fraction
                            centre_frequency = float(cf) * 1e6
                    except ValueError:
                        pass

            # check the fields make as much sense as we can here
            if cplx in ["cplx", "real"]:
                if cplx != "cplx":
                    complex_flag = False
                elif data_type in DataSource.supported_data_types:
                    # now convert the sample rate
                    try:
                        sample_rate_hz = float(sample_rate)
                        ok = True
                    except ValueError:
                        # don't exception just mark it as bad
                        ok = False

    return ok, data_type, complex_flag, sample_rate_hz, centre_frequency


class Input(DataSource.DataSource):

    def __init__(self,
                 file_name: str,
                 number_complex_samples: int,
                 data_type: str,
                 sample_rate: float,
                 centre_frequency: float):
        """
        File input class

        :param file_name: File name including path if required
        :param number_complex_samples: How many complex samples we require on each read
        :param data_type: The type of data we have in the file
        :param sample_rate: The sample rate this source is supposed to be working at, in Hz
        :param centre_frequency: The centre frequency this input is supposed to be at, in Hz
        """
        super().__init__(file_name, number_complex_samples, data_type, sample_rate, centre_frequency)

        self._wav_file = None
        self._file = None

        # first off, is this a wav file ?
        try:
            self._wav_file = wave.open(self._source, "rb")
            logger.debug(f"Opened wav {self._source} for reading")

            if self._wav_file.getnchannels() != 2:
                msgs = f"{module_type} is wav but not 2 channels"
                logger.error(msgs)
                raise ValueError(msgs)

            if self._wav_file.getsampwidth() > 2:
                msgs = f"{module_type} is wav but more than 2 bytes per sample"
                logger.error(msgs)
                raise ValueError(msgs)

            self._sample_rate = self._wav_file.getframerate()
            # we are assuming that someone is going to tell us what the data type in the wav file is
            # i.e. 16tbe or 16tle or even 8t
            logger.debug(f"Parameters for wav: cplx, {data_type}, {self._sample_rate}sps,")
        except wave.Error:
            # try again as a binary file
            try:
                self._file = open(self._source, "rb")
                logger.debug(f"Opened file {self._source} for reading")

                # see if we can set the sample rate and data type from the filename
                ok, data_type, complex_flag, sample_rate_hz, centre_frequency_fn = parse_filename(self._source)
                if ok:
                    if complex_flag:
                        self.set_sample_type(data_type)  # update the type of samples we expect
                        self._sample_rate = sample_rate_hz
                        if centre_frequency_fn != 0:
                            self._centre_frequency = centre_frequency_fn

                        logger.debug(f"Parameters from filename: cplx, {data_type}, "
                                     f"{sample_rate_hz:.0f}sps, "
                                     f"{self._centre_frequency:.0f}Hz")
                    else:
                        msgs = f"Error: Unsupported input of 'real' from {self._source}"
                        logger.error(msgs)
                        raise ValueError(msgs)
                else:
                    logger.debug(f"Failed to recover data type and sps from filename {self._source}")

                logger.debug(f"Using {self._data_type} and sps {self._sample_rate}Hz")
            except OSError as e:
                msgs = f"Failed to open input file, {e}"
                logger.error(msgs)
                raise ValueError(msgs)

        self._connected = True
        self._sleep_time = 0

    def set_sleep_time(self, sleep_time: float) -> None:
        """
        Set the delay we wait when we read samples from the file

        :param sleep_time: Time in seconds
        :return: None
        """
        self._sleep_time = sleep_time

    def read_cplx_samples(self) -> Tuple[np.array, float]:
        """
        Get complex float samples from the device
        :return: A tuple of a numpy array of complex samples and time in nsec
        """
        complex_data = None
        rx_time = 0
        if self._wav_file or self._file:
            try:
                if self._wav_file:
                    raw_bytes = self._wav_file.readframes(self._number_complex_samples)
                else:
                    # get just the number of bytes we needs
                    raw_bytes = self._file.read(self._bytes_per_snap)
                rx_time = time.time_ns()

                if len(raw_bytes) != self._bytes_per_snap:
                    self._connected = False
                    raise ValueError('End of file')

                time.sleep(self._sleep_time)
            except OSError as msg:
                msgs = f'OSError, {msg}'
                logger.error(msgs)
                raise ValueError(msgs)

            complex_data = self.unpack_data(raw_bytes)
        return complex_data, rx_time

    def close(self) -> None:
        if self._wav_file:
            self._wav_file.close()
        elif self._file:
            self._file.close()
        self._connected = False

    def reconnect(self) -> bool:
        """
        Rewind the input file

        :return: Boolean true if we managed to rewind the file
        """
        # Rewind the file
        self._connected = False
        if self._wav_file:
            self._wav_file.rewind()
            self._connected = True
        elif self._file:
            self._file.seek(0, 0)
            self._connected = True

        if self._connected:
            logger.debug(f"Rewound {self._source}")
        return self._connected
