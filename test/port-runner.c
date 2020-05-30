/***************************************

port-runner: exercise and validate your
  serial port traffic!

***************************************/

#include <stdio.h>
#include <unistd.h>
#include <stdlib.h>
#include <stdbool.h>
#include <errno.h>
#include <string.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <termios.h>
#include <pthread.h>
#include <signal.h>

/* Struct and data definitions */
struct device_opts
{
	const char *name;
	unsigned int baud_val;
};

/* Globals */
struct baud_entry
{
	char str[10];
	unsigned int val;
};

#define TOSTR(X) #X
#define TOENTRY(X) {#X, X}

struct baud_entry g_valid_bauds[] =
{
	TOENTRY(B50),
	TOENTRY(B75),
	TOENTRY(B110),
	TOENTRY(B134),
	TOENTRY(B150),
	TOENTRY(B200),
	TOENTRY(B300),
	TOENTRY(B600),
	TOENTRY(B1200),
	TOENTRY(B1800),
	TOENTRY(B2400),
	TOENTRY(B4800),
	TOENTRY(B9600),
	TOENTRY(B19200),
	TOENTRY(B38400),
	TOENTRY(B57600),
	TOENTRY(B115200),
	TOENTRY(B230400),
	TOENTRY(B460800),
	TOENTRY(B500000),
	TOENTRY(B576000),
	TOENTRY(B921600),
	TOENTRY(B1000000),
	TOENTRY(B1152000),
	TOENTRY(B1500000),
	TOENTRY(B2000000),
	TOENTRY(B2500000),
	TOENTRY(B3000000),
	TOENTRY(B3500000),
	TOENTRY(B4000000),
	{"", 0}	// empty string = end of list
};

const char *g_prog_name;

int g_fd_tx = -1;
int g_fd_rx = -1;

bool g_active;

unsigned char *g_data_out;
size_t g_data_out_len;
unsigned int g_sent_cnt = 0;
unsigned int g_miscompare_cnt = 0;

unsigned int g_delay;

#define errorout(...) fprintf(stderr, "ERROR: " __VA_ARGS__)

void usage(void)
{
	fprintf(stdout, "Usage: %s -t <transmit device> -r <receive device> -f <data filename> -d <delay in ms between sends>\n",
			g_prog_name);
}

void stop_it(int signum)
{
	g_active = false;
	fcntl(g_fd_rx, F_SETFL, FNDELAY);
}

void *tx_data(void *data)
{
	while (g_active)
	{
		//printf("TXTHREAD\n");
		write(g_fd_tx, g_data_out, g_data_out_len);
		g_sent_cnt++;
		printf(".");
		fflush(stdout);
		usleep(g_delay * 1000);
	}
	// printf("leaving TX\n");
	close(g_fd_tx);
	g_fd_tx = -1;
}

void *rx_data(void *data)
{
	unsigned char data_in[100];
	unsigned int data_out_index = 0;
	int ret;

	//fcntl(g_fd_rx, F_SETFL, 0);
	while (g_active)
	{
		ret = read(g_fd_rx, data_in, sizeof(data_in));
		if (ret < 1)
		{
			// errorout("RX error on read: %s (%d)\n", strerror(errno), errno);
		}
		else if (ret > 0)
		{
			// printf("RX saw %d bytes.... '%c'\n", ret, data_in[0]);
			if (memcmp(data_in, &g_data_out[data_out_index], ret))
			{
				g_miscompare_cnt++;
				data_out_index = 0;
			}
			else
			{
				data_out_index += ret;
				if (data_out_index >= g_data_out_len)
				{
					data_out_index -= g_data_out_len;
				}
			}
		}
	}
	// printf("leaving RX\n");
	close(g_fd_rx);
	g_fd_rx = -1;
}

unsigned int baud_lookup(const char *baud_str)
{
	unsigned int index = 0;
	while (strlen(g_valid_bauds[index].str) &&
			strncasecmp(baud_str, g_valid_bauds[index].str, strlen(g_valid_bauds[index].str)))
	{
		index++;
	}

	return g_valid_bauds[index].val;
}

int parse_device_opts(const char *device_str, struct device_opts *device_opts)
{
	char *d_str, *arg_ptr;
	int arg_pos = 0;
	int ret_val = 0;

	d_str = strdup(device_str);
	arg_ptr = strtok(d_str, ",");
	do
	{
		switch (arg_pos)
		{
			case 0: // name
				device_opts->name = arg_ptr;
				break;
			case 1: // baudrate
				device_opts->baud_val = baud_lookup(arg_ptr);
				if (!device_opts->baud_val)
				{
					errorout("invalid baud rate '%s'\n", arg_ptr);
					ret_val = -1;
				}
				break;
			default: // unsupported
				errorout("unsupported serial port option '%s'\n", arg_ptr);
				ret_val = -1;
				break;
		}
		
		arg_pos++;
	} while (arg_ptr = strtok(NULL, ","));

	return ret_val;
}

int free_device_opts(struct device_opts *device_opts)
{
	if (device_opts->name)
	{
		free((void *)device_opts->name);
	}

	return 0;
}

int open_serial(const struct device_opts *device_opts, int flags)
{
	int fd = -1;

	if (!device_opts->name)
	{
		errorout("device filename was not provided\n");
		usage();
		goto done;
	}

	fd = open(device_opts->name, flags);
	if (fd < 0)
	{
		errorout("could not open '%s': %s (%d)\n", device_opts->name, strerror(errno), errno);
		goto done;
	}

	struct termios opts;
	tcgetattr(fd, &opts);
	cfsetispeed(&opts, device_opts->baud_val);
	cfsetospeed(&opts, device_opts->baud_val);
	opts.c_cflag |= CLOCAL;
	opts.c_cflag |= CREAD;
	opts.c_cflag &= ~CRTSCTS;
	opts.c_lflag &= ~(ICANON | ECHO | ECHOE | ISIG);
	opts.c_oflag &= ~OPOST;

	tcsetattr(fd, TCSANOW, &opts);

done:
	return fd;
}

int main(int argc, char *argv[])
{
	pthread_t tx_thread, rx_thread;
	int opt;
	struct device_opts tx_device = { 0 };
	struct device_opts rx_device = { 0 };
	const char *data_filename = NULL;
	g_prog_name = argv[0];
	int ret;
	int exit_val = 0;

	while ((opt = getopt(argc, argv, "t:r:f:d:h")) != -1)
	{
		switch(opt)
		{
			case 't':	// Transmit port
				if (parse_device_opts(optarg, &tx_device))
				{
					goto done;
				}
				break;
			case 'r':	// Receive port
				if (parse_device_opts(optarg, &rx_device))
				{
					goto done;
				}
				break;
			case 'f':	// File of data pattern to send
				data_filename = optarg;
				break;
			case 'd':	// Delay (in ms) between sending data pattern
				g_delay = (unsigned int)strtol(optarg, NULL, 10);
				if (errno == EINVAL)
				{
					errorout("invaid non-integer value for delay\n");
					usage();
					exit_val = -1;
					goto done;
				}
				break;
			case 'h':	// Help
				usage();
				goto done;
				break;
			default:
				// unrecognized option
				usage();
				exit_val = -1;
				goto done;
				break;
		}
	}

	// Ensure we have a least one port baud rate setting provided...
	if (tx_device.baud_val && !rx_device.baud_val)
	{
		rx_device.baud_val = tx_device.baud_val;
	}
	else if (!tx_device.baud_val && rx_device.baud_val)
	{
		tx_device.baud_val = rx_device.baud_val;
	}
	else if (!tx_device.baud_val || !rx_device.baud_val)
	{
		errorout("missing baud rate\n");
		usage();
		exit_val = -2;
		goto done;
	}

	// Verify we don't have different baud rates specified (but technically we could support this)
	if (tx_device.baud_val != rx_device.baud_val)
	{
		errorout("differing baud rates specified\n");
		exit_val = -2;
		goto done;
	}

	// Open TX device...
	g_fd_tx = open_serial(&tx_device, O_WRONLY | O_NOCTTY | O_NDELAY);
	if (g_fd_tx < 0)
	{
		exit_val = -3;
		goto done;
	}

	// Open RX device...
	g_fd_rx = open_serial(&rx_device, O_RDONLY | O_NOCTTY | O_NDELAY);
	//g_fd_rx = open_serial(&rx_device, O_RDONLY | O_NOCTTY | O_NDELAY | O_NONBLOCK);
	if (g_fd_rx < 0)
	{
		exit_val = -3;
		goto done;
	}

	/***********************
	 * Load in file contents
	 **********************/
	int fd_data = open(data_filename, O_RDONLY);
	if (fd_data < 0)
	{
		errorout("could not locate data file '%s': %s (%d)\n", data_filename, strerror(errno), errno);
		exit_val = -4;
		goto done;
	}
	struct stat file_stat;
	ret = fstat(fd_data, &file_stat);
	if (ret < 0)
	{
		errorout("could not get stats on data file '%s': %s (%d)\n", data_filename, strerror(errno), errno);
		exit_val = -5;
		goto done;
	}
	g_data_out_len = file_stat.st_size;
	g_data_out = malloc(g_data_out_len);
	if (!g_data_out)
	{
		errorout("failed to allocate memory: %s (%d)\n", strerror(errno), errno);
		exit_val = -6;
		goto done;
	}
	int read_bytes = 0;
	while (read_bytes < g_data_out_len)
	{
		ret = read(fd_data, &g_data_out[read_bytes], g_data_out_len - read_bytes);
		read_bytes += ret;
	}
	close(fd_data);
	fd_data = -1;

	printf("Loaded %u bytes of data from '%s', leaving %u milliseconds between sends...\n",
			read_bytes, data_filename, g_delay);

	g_active = true;
	signal(SIGINT, stop_it);
	printf("Sending traffic...");
	pthread_create(&rx_thread, NULL, rx_data, NULL);
	pthread_create(&tx_thread, NULL, tx_data, NULL);
	pthread_join(tx_thread, NULL);
	pthread_join(rx_thread, NULL);

	printf("\n\nDone.");
	printf("\n\nData sent %u times, failed compares: %u\n", g_sent_cnt, g_miscompare_cnt);

done:
	free_device_opts(&tx_device);
	free_device_opts(&rx_device);
	if (g_data_out)
	{
		free(g_data_out);
	}
	if (g_fd_tx >= 0)
	{
		close(g_fd_tx);
	}
	if (g_fd_rx >= 0)
	{
		close(g_fd_rx);
	}
	if (fd_data >= 0)
	{
		close(fd_data);
	}
	return exit_val;
}
