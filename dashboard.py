#!/usr/bin/python
"""
n1mm_view dashboard
This program displays QSO statistics collected by the collector.
"""

import logging
import os
import pygame
import sqlite3
import time
import threading

import matplotlib
#  This makes the code analyzer angry, as python standards say to put imports ahead of all executable code.
#  But... it MUST be RIGHT HERE so matplotlib does not try to use the wrong backend.
matplotlib.use('Agg')
import matplotlib.backends.backend_agg as agg
import matplotlib.pyplot as plt
from matplotlib.dates import HourLocator, DateFormatter

from n1mm_view_constants import *
from n1mm_view_config import *

__author__ = 'Jeffrey B. Otterson, N1KDO'
__copyright__ = 'Copyright 2016 Jeffrey B. Otterson'
__license__ = 'Simplified BSD'

RED = pygame.Color('#ff0000')
GREEN = pygame.Color('#33cc33')
BLUE = pygame.Color('#3333cc')
YELLOW = pygame.Color('#cccc00')
CYAN = pygame.Color('#00cccc')
BLACK = pygame.Color('#000000')
WHITE = pygame.Color('#ffffff')
GRAY = pygame.Color('#cccccc')

# Initialize font support
pygame.font.init()
view_font = pygame.font.Font('veraMoBd.ttf', 64)
bigger_font = pygame.font.SysFont('veraMoBd.ttf', 180)
view_font_height = view_font.get_height()

LOGO_IMAGE_INDEX = 0
QSO_COUNTS_TABLE_INDEX = 1
QSO_RATES_TABLE_INDEX = 2
QSO_OPERATORS_PIE_INDEX = 3
QSO_OPERATORS_TABLE_INDEX = 4
QSO_STATIONS_PIE_INDEX = 5
QSO_BANDS_PIE_INDEX = 6
QSO_MODES_PIE_INDEX = 7
QSO_RATE_CHART_IMAGE_INDEX = 8
IMAGE_COUNT = 9

logging.basicConfig(format='%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s', datefmt='%Y-%m-%d %H:%M:%S',
                    level=logging.INFO)
logging.Formatter.converter = time.gmtime


def load_data(size, images, crawl_messages, last_qso_timestamp):
    """
    load data from the database tables
    """
    logging.debug('load data')

    qso_operators = []
    qso_stations = []
    qso_band_modes = []
    operator_qso_rates = []
    qsos_per_hour = []

    db = None

    try:
        logging.debug('connecting to database')
        db = sqlite3.connect(DATABASE_FILENAME)
        cursor = db.cursor()
        logging.debug('database connected')

        # get timestamp from the last record in the database
        cursor.execute('SELECT timestamp, callsign, exchange, section, operator.name, band_id \n'
                       'FROM qso_log JOIN operator WHERE operator.id = operator_id \n'
                       'ORDER BY timestamp DESC LIMIT 1')
        last_qso_time = int(time.time()) - 60
        message = ''
        for row in cursor:
            last_qso_time = row[0]
            message = 'Last QSO: %s %s %s on %s by %s at %s' % (row[1], row[2], row[3], Bands.BANDS_TITLE[row[5]], row[4],
                                                                datetime.datetime.utcfromtimestamp(row[0]).strftime('%H:%M:%S'))
            logging.debug(message)

        data_updated = False

        logging.debug('old_timestamp = %d, timestamp = %d' ,last_qso_timestamp, last_qso_time)
        if last_qso_time != last_qso_timestamp:
            logging.debug('data updated!')
            data_updated = True
            crawl_messages.set_message(3, message)
            crawl_messages.set_message_colors(3, CYAN, BLACK)

            # load qso_operators
            logging.debug('Load QSOs by Operator')
            qso_operators = []
            cursor.execute('SELECT name, COUNT(operator_id) AS qso_count \n'
                           'FROM qso_log JOIN operator ON operator.id = operator_id \n'
                           'GROUP BY operator_id ORDER BY qso_count desc;')
            for row in cursor:
                qso_operators.append((row[0], row[1]))

            # load qso_stations
            logging.debug('Load QSOs by Station')
            qso_stations = []
            cursor.execute('SELECT name, COUNT(station_id) AS qso_count \n'
                           'FROM qso_log JOIN station ON station.id = station_id GROUP BY station_id;')
            for row in cursor:
                qso_stations.append((row[0], row[1]))

            qso_band_modes = [[0] * 4 for _ in Bands.BANDS_LIST]

            cursor.execute('SELECT COUNT(*), band_id, mode_id FROM qso_log GROUP BY band_id, mode_id;')
            for row in cursor:
                qso_band_modes[row[1]][Modes.MODE_TO_SIMPLE_MODE[row[2]]] = row[0]

            # calculate QSOs per hour rate for all active operators
            # the higher the slice_minutes number is, the better the
            # resolution of the rate, but the slower to update.
            slice_minutes = 10
            slices_per_hour = 60 / slice_minutes

            # get timestamp from the first record in the database
            logging.debug('Loading first and last QSO timestamps')
            cursor.execute('SELECT timestamp FROM qso_log ORDER BY timestamp LIMIT 1')
            first_qso_time = int(time.time()) - 60
            for row in cursor:
                first_qso_time = row[0]

            start_time = last_qso_time - slice_minutes * 60

            # load QSOs per Hour by Operator
            logging.debug('Load QSOs per Hour by Operator')
            cursor.execute('SELECT operator.name, COUNT(operator_id) qso_count FROM qso_log\n'
                           'JOIN operator ON operator.id = operator_id\n'
                           'WHERE timestamp >= ? AND timestamp <= ?\n'
                           'GROUP BY operator_id ORDER BY qso_count DESC LIMIT 10;', (start_time, last_qso_time))
            operator_qso_rates = [['Operator', 'Rate']]
            total = 0
            for row in cursor:
                rate = row[1] * slices_per_hour
                total += rate
                operator_qso_rates.append([row[0], '%4d' % rate])
            operator_qso_rates.append(['Total', '%4d' % total])

            qsos_per_hour = []
            qsos_by_band = [0] * Bands.count()
            slice_minutes = 15
            slices_per_hour = 60 / slice_minutes
            window_seconds = slice_minutes * 60

            # load QSO rates per Hour by Band
            logging.debug('Load QSOs per Hour by Band')
            cursor.execute('SELECT timestamp / %d * %d AS ts, band_id, COUNT(*) AS qso_count \n'
                           'FROM qso_log GROUP BY ts, band_id;' % (window_seconds, window_seconds))
            for row in cursor:
                if len(qsos_per_hour) == 0:
                    qsos_per_hour.append([0] * Bands.count())
                    qsos_per_hour[-1][0] = row[0]
                while qsos_per_hour[-1][0] != row[0]:
                    ts = qsos_per_hour[-1][0] + window_seconds
                    qsos_per_hour.append([0] * Bands.count())
                    qsos_per_hour[-1][0] = ts
                qsos_per_hour[-1][row[1]] = row[2] * slices_per_hour
                qsos_by_band[row[1]] += row[2]

            for rec in qsos_per_hour:
                rec[0] = datetime.datetime.utcfromtimestamp(rec[0])
                t = rec[0].strftime('%H:%M:%S')

            # load QSOs by Section
            logging.debug('Load QSOs by Section')
            qsos_by_section = []
            cursor.execute('SELECT section, COUNT(section) AS qsos FROM qso_log GROUP BY section ORDER BY section;')
            for row in cursor:
                qsos_by_section.append((row[0], row[1]))

        logging.debug('load data done')
    except sqlite3.OperationalError as error:
        logging.exception(error)
        logging.warn('could not load data, database error')
    if db is not None:
        db.close()

    if data_updated:
        images[QSO_COUNTS_TABLE_INDEX] = qso_summary_table(size, qso_band_modes)
        images[QSO_RATES_TABLE_INDEX] = qso_rates_table(size, operator_qso_rates)
        images[QSO_OPERATORS_PIE_INDEX] = qso_operators_graph(size, qso_operators)
        images[QSO_OPERATORS_TABLE_INDEX] = qso_operators_table(size, qso_operators)
        images[QSO_STATIONS_PIE_INDEX] = qso_stations_graph(size, qso_stations)
        images[QSO_BANDS_PIE_INDEX] = qso_bands_graph(size, qso_band_modes)
        images[QSO_MODES_PIE_INDEX] = qso_modes_graph(size, qso_band_modes)
        images[QSO_RATE_CHART_IMAGE_INDEX] = qso_rates_chart(size, qsos_per_hour)

    return last_qso_time


def init_display():
    """
    set up the pygame display, full screen
    """

    # Check which frame buffer drivers are available
    # Start with fbcon since directfb hangs with composite output
    drivers = ['fbcon', 'directfb', 'svgalib', 'directx', 'windib']
    found = False
    for driver in drivers:
        # Make sure that SDL_VIDEODRIVER is set
        if not os.getenv('SDL_VIDEODRIVER'):
            os.putenv('SDL_VIDEODRIVER', driver)
        try:
            pygame.display.init()
        except pygame.error:
            #  logging.warn('Driver: %s failed.' % driver)
            continue
        found = True
        logging.info('using %s driver', driver)
        break

    if not found:
        raise Exception('No suitable video driver found!')

    size = (pygame.display.Info().current_w, pygame.display.Info().current_h)
    if driver != 'directx':  # debugging hack runs in a window on Windows
        pygame.mouse.set_visible(0)
        screen = pygame.display.set_mode(size, pygame.FULLSCREEN)
    else:
        logging.info('running in windowed mode')
        size = (1680, 1050)
        screen = pygame.display.set_mode(size)

    logging.info('display size: %d x %d', size[0], size[1])
    # Clear the screen to start
    screen.fill(BLACK)
    return screen, size


def make_pie(size, values, labels, title):
    """
    make a pie chart using matplotlib.
    return the chart as a pygame surface
    make the pie chart a square that is as tall as the display.
    """
    logging.debug('make_pie(...,...,%s)', title)
    inches = size[1] / 100.0
    fig = plt.figure(figsize=(inches, inches), dpi=100, tight_layout=True, facecolor='#000000')
    ax = fig.add_subplot(111)
    ax.pie(values, labels=labels, autopct='%1.1f%%', textprops={'color': 'white'})
    ax.set_title(title, color='white', size='xx-large', weight='bold')
    handles, labels = ax.get_legend_handles_labels()
    legend = ax.legend(handles[0:5], labels[0:5], title='Top %s' % title, loc='best')
    frame = legend.get_frame()
    frame.set_color((0, 0, 0, 0.75))
    frame.set_edgecolor('w')
    legend.get_title().set_color('w')
    for text in legend.get_texts():
        plt.setp(text, color='w')

    canvas = agg.FigureCanvasAgg(fig)
    canvas.draw()
    renderer = canvas.get_renderer()
    raw_data = renderer.tostring_rgb()
    plt.close(fig)

    canvas_size = canvas.get_width_height()
    surf = pygame.image.fromstring(raw_data, canvas_size, "RGB")
    logging.debug('make_pie(...,...,%s) done', title)
    return surf


def show_graph(screen, size, surf):
    """
    display a surface on the screen.
    """
    logging.debug('show_graph()')
    xoffset = (size[0] - surf.get_width()) / 2
    # yoffset = (graph_size[1] - surf.get_height()) / 2
    yoffset = 0
    screen.fill((0, 0, 0))
    screen.blit(surf, (xoffset, yoffset))
    logging.debug('show_graph() done')


def qso_operators_graph(size, qso_operators):
    """
    create the QSOs by Operators pie chart
    """
    # calculate QSO by Operator
    labels = []
    values = []
    for d in qso_operators:
        labels.append(d[0])
        values.append(d[1])
    return make_pie(size, values, labels, "QSOs by Operator")


def qso_operators_table(size, qso_operators):
    """
    create the Top 5 QSOs by Operators table
    """
    count = 0
    cells = [['Operator', 'QSOs']]
    for d in qso_operators:
        cells.append(['%s' % d[0], '%5d' % d[1]])
        count += 1
        if count >= 5:
            break
    return draw_table(size, cells, "Top 5 Operators", bigger_font)


def qso_stations_graph(size, qso_stations):
    """
    create the QSOs by Station pie chart
    """
    labels = []
    values = []
    # for d in qso_stations:
    for d in sorted(qso_stations, key=lambda count: count[1], reverse=True):
        labels.append(d[0])
        values.append(d[1])
    return make_pie(size, values, labels, "QSOs by Station")


def qso_bands_graph(size, qso_band_modes):
    """
    create the QSOs by Band pie chart
    """
    labels = []
    values = []
    band_data = [[band, 0] for band in range(0, Bands.count())]
    for i in range(0, Bands.count()):
        band_data[i][1] = qso_band_modes[i][1] +  qso_band_modes[i][2] +  qso_band_modes[i][3]

    for bd in sorted(band_data[1:], key=lambda count: count[1], reverse=True):
        if bd[1] > 0:
            labels.append(Bands.BANDS_TITLE[bd[0]])
            values.append(bd[1])
    return make_pie(size, values, labels, "QSOs by Band")


def qso_modes_graph(size, qso_band_modes):
    """
    create the QSOs by Mode pie chart
    """
    labels = []
    values = []
    mode_data = [[mode, 0] for mode in range(0, len(Modes.SIMPLE_MODES_LIST))]
    for i in range(0, Bands.count()):
        for mode_num in range(1, len(Modes.SIMPLE_MODES_LIST)):
            mode_data[mode_num][1] += qso_band_modes[i][mode_num]

    for md in sorted(mode_data[1:], key=lambda count: count[1], reverse=True):
        if md[1] > 0:
            labels.append(Modes.SIMPLE_MODES_LIST[md[0]])
            values.append(md[1])
    return make_pie(size, values, labels, "QSOs by Mode")


def qso_summary_table(size, qso_band_modes):
    """
    create the QSO Summary Table
    """
    return draw_table(size, make_score_table(qso_band_modes), "QSOs Summary")


def qso_rates_table(size, operator_qso_rates):
    """
    create the QSO Rates by Operator table
    """
    return draw_table(size, operator_qso_rates, "QSO/Hour Rates")


def qso_rates_chart(size, qsos_per_hour):
    """
    make the qsos per hour per band chart
    returns a pygame surface
    """
    title = 'QSOs per Hour by Band'
    qso_counts = [[], [], [], [], [], [], [], [], [], []]
    data_valid = len(qsos_per_hour) != 0

    for qpm in qsos_per_hour:
        for i in range(0, Bands.count()):
            c = qpm[i]
            cl = qso_counts[i]
            cl.append(c)

    logging.debug('make_plot(...,...,%s)', title)
    width_inches = size[0] / 100.0
    height_inches = size[1] / 100.0
    fig = plt.Figure(figsize=(width_inches, height_inches), dpi=100, tight_layout=True, facecolor='black')
    ax = fig.add_subplot(111, axisbg='black')
    ax.set_title(title, color='white', size='xx-large', weight='bold')

    if data_valid:
        dates = matplotlib.dates.date2num(qso_counts[0])
        colors = ['r', 'g', 'b', 'c', 'm', 'y', '#ff9900', '#00ff00', '#663300']
        labels = Bands.BANDS_TITLE[1:]
        # ax.set_autoscalex_on(True)
        start_date = matplotlib.dates.date2num(EVENT_START_TIME)
        end_date =  matplotlib.dates.date2num(EVENT_END_TIME)
        ax.set_xlim(start_date, end_date)

        ax.stackplot(dates, qso_counts[1], qso_counts[2], qso_counts[3], qso_counts[4], qso_counts[5], qso_counts[6],
                     qso_counts[7], qso_counts[8], qso_counts[9], labels=labels, colors=colors, linewidth=0.2)
        ax.grid(True)
        legend = ax.legend(loc='best', ncol=Bands.count() - 1)
        legend.get_frame().set_color((0, 0, 0, 0))
        legend.get_frame().set_edgecolor('w')
        for text in legend.get_texts():
            plt.setp(text, color='w')
        ax.spines['left'].set_color('w')
        ax.spines['right'].set_color('w')
        ax.spines['top'].set_color('w')
        ax.spines['bottom'].set_color('w')
        ax.tick_params(axis='y', colors='w')
        ax.tick_params(axis='x', colors='w')
        ax.set_ylabel('QSO Rate/Hour', color='w', size='x-large', weight='bold')
        ax.set_xlabel('UTC Hour', color='w', size='x-large', weight='bold')
        hour_locator = HourLocator()
        hour_formatter = DateFormatter('%H')
        ax.xaxis.set_major_locator(hour_locator)
        ax.xaxis.set_major_formatter(hour_formatter)

    canvas = agg.FigureCanvasAgg(fig)
    canvas.draw()
    renderer = canvas.get_renderer()
    raw_data = renderer.tostring_rgb()
    plt.close(fig)

    canvas_size = canvas.get_width_height()
    surf = pygame.image.fromstring(raw_data, canvas_size, "RGB")

    return surf


def draw_table(size, cell_text, title, font=None):
    """
    draw a table
    """
    logging.debug('draw_table(...,%s)', title)
    font_size = 100
    if font is None:
        table_font = view_font
    else:
        table_font = font

    text_y_offset = 4
    text_x_offset = 4
    line_width = 4

    # calculate column widths
    rows = len(cell_text)
    cols = len(cell_text[1])
    col_widths = [0] * cols
    widest = 0
    for row in cell_text:
        col_num = 0
        for col in row:
            text_size = table_font.size(col)
            text_width = text_size[0] + 2 * text_x_offset
            if text_width > col_widths[col_num]:
                col_widths[col_num] = text_width
            if text_width > widest:
                widest = text_width
            col_num += 1

    header_width = table_font.size(title)[0]
    table_width = sum(col_widths) + line_width / 2
    row_height = table_font.get_height()
    height = (rows + 1) * row_height + line_width / 2
    surface_width = table_width
    x_offset = 0
    if header_width > surface_width:
        surface_width = header_width
        x_offset = (header_width - table_width) / 2

    surf = pygame.Surface((surface_width, height))

    surf.fill(BLACK)
    text_color = GRAY
    head_color = WHITE
    grid_color = GRAY

    # draw the title
    text = table_font.render(title, True, head_color)
    textpos = text.get_rect()
    textpos.y = 0
    textpos.centerx = surface_width / 2
    surf.blit(text, textpos)

    starty = row_height
    origin = (x_offset, row_height)

    # draw the grid
    x = x_offset
    y = starty
    for r in range(0, rows + 1):
        sp = (x, y)
        ep = (x + table_width, y)
        pygame.draw.line(surf, grid_color, sp, ep, line_width)
        y += row_height

    x = x_offset
    y = starty
    for cw in col_widths:
        sp = (x, y)
        ep = (x, y + height)
        pygame.draw.line(surf, grid_color, sp, ep, line_width)
        x += cw
    sp = (x, y)
    ep = (x, y + height)
    pygame.draw.line(surf, grid_color, sp, ep, line_width)

    y = starty + text_y_offset
    row_number = 0
    for row in cell_text:
        row_number += 1
        x = origin[0]
        column_number = 0
        for col in row:
            x += col_widths[column_number]
            column_number += 1
            if row_number == 1 or column_number == 1:
                text = table_font.render(col, True, head_color)
            else:
                text = table_font.render(col, True, text_color)
            textpos = text.get_rect()
            textpos.y = y - text_y_offset
            textpos.right = x - text_x_offset
            surf.blit(text, textpos)
        y += row_height
    logging.debug('draw_table(...,%s) done', title)
    return surf


def make_score_table(qso_band_modes):
    """
    create the score table from data
    """
    cell_data = [[0 for m in Modes.SIMPLE_MODES_LIST] for b in Bands.BANDS_TITLE]

    for band_num in range(1, Bands.count()):
        for mode_num in range(1,len(Modes.SIMPLE_MODES_LIST)):
            cell_data[band_num][mode_num] = qso_band_modes[band_num][mode_num]
            cell_data[band_num][0] += qso_band_modes[band_num][mode_num]
            cell_data[0][mode_num] += qso_band_modes[band_num][mode_num]

    total = 0
    for c in cell_data[0][1:]:
        total += c
    cell_data[0][0] = total

    # the totals are in the 0th row and 0th column, move them to last.
    cell_text = [['', '   CW', 'Phone', ' Data', 'Total']]
    band_num = 0
    for row in cell_data[1:]:
        band_num += 1
        row_text = ['%5s' % Bands.BANDS_TITLE[band_num]]

        for col in row[1:]:
            row_text.append('%5d' % col)
        row_text.append('%5d' % row[0])
        cell_text.append(row_text)

    row = cell_data[0]
    row_text = ['Total']
    for col in row[1:]:
        row_text.append('%5d' % col)
    row_text.append('%5d' % row[0])
    cell_text.append(row_text)
    return cell_text


def show_page(screen, size, image):
    """
    show a chart image
    """
    logging.debug("show_page()")
    if image is not None:
        show_graph(screen, size, image)
    logging.debug('show_page() done')


def deltatime_to_string(delta_time):
    """
    return a string that represents delta time
    """
    seconds = delta_time.total_seconds()
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if days != 0:
        return '%d days, %02d:%02d:%02d' % (days, hours, minutes, seconds)
    else:
        return '%02d:%02d:%02d' % (hours, minutes, seconds)


def update_crawl_message(crawl_messages):
    now = datetime.datetime.utcnow()
    crawl_messages.set_message(0, EVENT_NAME)
    crawl_messages.set_message_colors(0, BLUE, BLACK)
    crawl_messages.set_message(1, datetime.datetime.strftime(now, '%H:%M:%S'))
    if now < EVENT_START_TIME:
        delta = EVENT_START_TIME - now
        crawl_messages.set_message(2, 'The Contest starts in ' + deltatime_to_string(delta))
        crawl_messages.set_message_colors(2, GREEN, BLACK)
    elif now < EVENT_END_TIME:
        delta = EVENT_END_TIME - now
        crawl_messages.set_message(2, 'The contest ends in ' + deltatime_to_string(delta))
        crawl_messages.set_message_colors(2, YELLOW, BLACK)
    else:
        crawl_messages.set_message(2, 'The contest is over.')
        crawl_messages.set_message_colors(2, RED, BLACK)


class CrawlMessages:
    """
    class to manage a crawl of varied text messages on the bottom of the display
    """
    def __init__(self, screen, size):
        self.screen = screen
        self.size = size
        self.messages = [''] * 10
        self.message_colors = [(GREEN, BLACK)] * 10
        self.message_surfaces = None
        self.last_added_index = -1
        self.first_x = -1

    def set_message(self, index, message):
        if index >=0 and index < len(self.messages):
            self.messages[index] = message

    def set_message_colors(self, index, fg, bg):
        if index >=0 and index < len(self.messages):
            self.message_colors[index] = (fg, bg)

    def crawl_message(self):
        if self.message_surfaces is None:
            logging.info('creating surfaces')
            self.message_surfaces = [view_font.render(' ' + self.messages[0] + ' ', True,
                                                      self.message_colors[0][0],
                                                      self.message_colors[0][1])]
            self.first_x = self.size[0]
            self.last_added_index = 0

        self.first_x -= 1
        rect = self.message_surfaces[0].get_rect()
        if self.first_x + rect.width < 0:
            self.message_surfaces = self.message_surfaces[1:]
            self.first_x = 0
        x = self.first_x
        for surf in self.message_surfaces:
            rect = surf.get_rect()
            x = x + rect.width

        while x < self.size[0]:
            self.last_added_index += 1
            if self.last_added_index >= len(self.messages):
                self.last_added_index = 0
            if self.messages[self.last_added_index] != '':
                surf = view_font.render(' ' + self.messages[self.last_added_index] + ' ', True,
                                        self.message_colors[self.last_added_index][0],
                                        self.message_colors[self.last_added_index][1])
                rect = surf.get_rect()
                self.message_surfaces.append(surf)
                x += rect.width

        x = self.first_x
        for surf in self.message_surfaces:
            rect = surf.get_rect()
            rect.bottom = self.size[1] - 1
            rect.left = x
            self.screen.blit(surf, rect)
            x += rect.width
            if x >= self.size[0]:
                break


class UpdateThread (threading.Thread):
    """
    run the chart updates in their own thread, so the UI does not block.
    """
    def __init__(self, size, images, crawl_messages):
        threading.Thread.__init__(self)
        # super(UpdateThread, self).__init__()
        self.event = threading.Event()
        self.size = size
        self.images = images
        self.crawl_messages = crawl_messages
        self.last_qso_timestamp = 0

    def run(self):
        while not self.event.is_set():
            t0 = time.time()
            self.last_qso_timestamp = load_data(self.size, self.images, self.crawl_messages, self.last_qso_timestamp)
            t1 = time.time()
            delta = t1 - t0
            update_delay = DATA_DWELL_TIME - delta
            if update_delay < 0:
                update_delay = DATA_DWELL_TIME
            logging.debug('Next data update in %f seconds', update_delay)
            self.event.wait(update_delay)


def main():
    logging.info('dashboard startup')
    images = [None] * IMAGE_COUNT

    screen, size = init_display()
    display_size = (size[0], size[1] - view_font_height)

    logging.debug('display setup')

    images[LOGO_IMAGE_INDEX] = pygame.image.load('logo.png')

    crawl_messages = CrawlMessages(screen, size)
    update_crawl_message(crawl_messages)

    thread = UpdateThread(display_size, images, crawl_messages)
    thread.start()

    image_index = LOGO_IMAGE_INDEX
    show_page(screen, size, images[LOGO_IMAGE_INDEX])

    milliseconds = 0
    update_time = 20
    pygame.time.set_timer(pygame.USEREVENT, update_time)
    run = True

    display_update_timer = DISPLAY_DWELL_TIME
    data_update_timer = DATA_DWELL_TIME

    while run:
        for event in [pygame.event.wait()] + pygame.event.get():
            if event.type == pygame.QUIT:
                run = False
                break
            elif event.type == pygame.USEREVENT:
                milliseconds += update_time
                if milliseconds >= 1000:
                    # one second tick
                    milliseconds = 0
                    data_update_timer -= 1
                    if data_update_timer < 1:
                        #thread = UpdateThread(display_size, images, crawl_messages)
                        #thread.start()
                        data_update_timer = DATA_DWELL_TIME
                    display_update_timer -= 1
                    if display_update_timer < 1:
                        display_update_timer = DISPLAY_DWELL_TIME
                        image_index += 1
                        if image_index >= len(images):
                            image_index = 0
                        show_page(screen, size, images[image_index])
                    update_crawl_message(crawl_messages)
                crawl_messages.crawl_message()
                pygame.display.flip()
            elif event.type == pygame.KEYDOWN:
                if event.key == ord('q'):
                    logging.debug('Q key pressed')
                    run = False
                elif event.key == ord('n') or event.key == 275:
                    logging.debug('N key pressed')
                    image_index += 1
                    if image_index >= len(images):
                        image_index = 0
                    show_page(screen, size, images[image_index])
                    display_update_timer = DISPLAY_DWELL_TIME
                elif event.key == ord('p') or event.key == 276:
                    logging.debug('P key pressed')
                    image_index -= 1
                    if image_index < 0:
                        image_index = len(images) - 1
                    show_page(screen, size, images[image_index])
                    display_update_timer = DISPLAY_DWELL_TIME
                else:
                    logging.debug('event key=%d', event.key)


    logging.debug('stopping update thread')
    thread.event.set()
    logging.debug('waiting for update thread to stop...')
    thread.join(60)
    logging.debug('update thread has stopped.')

    pygame.time.set_timer(pygame.USEREVENT, 0)

    pygame.display.quit()

    logging.info('dashboard exit')


if __name__ == '__main__':
    main()
