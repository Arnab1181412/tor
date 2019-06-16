import os
import time

# The `import tor` lines is necessary because `tor.__SELF_NAME__` is
# set here. Reason: https://gist.github.com/TheLonelyGhost/9dbe810c42d8f2edcf3388a8b19519e1
import tor
from tor import __version__
from tor.core.config import config
from tor.core.helpers import run_until_dead
from tor.core.inbox import check_inbox
from tor.core.initialize import build_bot
from tor.helpers.flair import set_meta_flair_on_other_posts
from tor.helpers.threaded_worker import threaded_check_submissions


##############################
NOOP_MODE = bool(os.getenv('NOOP_MODE', ''))
DEBUG_MODE = bool(os.getenv('DEBUG_MODE', ''))
##############################

# Patreon Dedications:
#
# Through our work supported by Grafeas Group Ltd., some people see
# fit to help us keep the lights on. Of those helpful souls, even
# fewer gift $50 or more and they have earned their place in the
# following list. For reference, the link can be found here:
# https://www.patreon.com/grafeasgroup
# List is in date order.
#
# Jake L (2017-11-17)
# Michael W (2017-11-27)

# Musical Dedications:
#
# This program is dedicated to the below artists; their music has
# served as the soundtrack for the continued development of u/ToR.
# List is in alphabetical order. Anyone who contributes to this
# codebase is invited to add their tunes!
#
# Alison Wonderland
# Aramanthe
# Braxton Burks
# Caravan Palace
# David Bowie
# Hiromi
# Girl Talk
# Icon for Hire
# Inverness
# K-391
# Lady Gaga
# Neon Hitch
# The Beatles
# The Killers
# Two Door Cinema Club
#
#
# Streams:
# https://www.youtube.com/watch?v=hX3j0sQ7ot8  # he's dead, Jim


def noop(cfg):
    pass


def run(config):
    """
    Primary routine.

    :param config: Global config dict, supplied by tor_core.
    :return: None.
    """
    check_inbox(config)

    threaded_check_submissions(config)

    set_meta_flair_on_other_posts(config)

    if config.debug_mode:
        time.sleep(60)


def main():
    config.debug_mode = DEBUG_MODE

    if config.debug_mode:
        bot_name = 'debug'
    else:
        bot_name = os.environ.get('BOT_NAME', 'bot')

    build_bot(bot_name, __version__, full_name='u/ToR')
    config.perform_header_check = True

    tor.__SELF_NAME__ = config.r.user.me().name
    if tor.__SELF_NAME__ not in tor.__BOT_NAMES__:
        tor.__BOT_NAMES__.append(tor.__SELF_NAME__)

    if NOOP_MODE:
        run_until_dead(noop)
    else:
        run_until_dead(run)


if __name__ == '__main__':
    main()
