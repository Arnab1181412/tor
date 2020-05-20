import logging
import random
from typing import Tuple

from praw.exceptions import APIException, ClientException  # type: ignore
from praw.models import Comment, Message, Submission  # type: ignore

from tor import __BOT_NAMES__
from tor.core.blossom_wrapper import BlossomStatus
from tor.core.config import Config
from tor.core.helpers import (_, clean_id, get_parent_post_id, get_wiki_page,
                              remove_if_required, send_reddit_reply, send_to_modchat)
from tor.core.users import User
from tor.core.validation import verified_posted_transcript
from tor.helpers.flair import flair, flair_post, update_user_flair
from tor.helpers.reddit_ids import is_removed
from tor.strings import translation

i18n = translation()
log = logging.getLogger(__name__)


def coc_accepted(post: Comment, cfg: Config) -> bool:
    """
    Verifies that the user is in the Redis set "accepted_CoC".

    :param post: the Comment object containing the claim.
    :param cfg: the global config dict.
    :return: True if the user has accepted the Code of Conduct, False if they
        haven't.
    """
    return cfg.redis.sismember('accepted_CoC', post.author.name) == 1


def process_coc(post: Comment, cfg: Config) -> None:
    """
    Adds the username of the redditor to the db as accepting the code of
    conduct.

    :param post: The Comment object containing the claim.
    :param cfg: the global config dict.
    :return: None.
    """
    result = cfg.redis.sadd('accepted_CoC', post.author.name)

    modchat_emote = random.choice([
        ':tada:',
        ':confetti_ball:',
        ':party-lexi:',
        ':party-parrot:',
        ':+1:',
        ':trophy:',
        ':heartpulse:',
        ':beers:',
        ':gold:',
        ':upvote:',
        ':coolio:',
        ':derp:',
        ':lenny1::lenny2:',
        ':panic:',
        ':fidget-spinner:',
        ':fb-like:'
    ])

    # Have they already been added? If 0, then just act like they said `claim`
    # instead. If they're actually new, then send a message to slack.
    if result == 1:
        send_to_modchat(
            f'<{i18n["urls"]["reddit_url"].format("/user/" + post.author.name)}|u/{post.author.name}>'
            f' has just'
            f' <{i18n["urls"]["reddit_url"].format(post.context)}|accepted the CoC!>'
            f' {modchat_emote}',
            cfg,
            channel='new_volunteers'
        )
    process_claim(post, cfg, first_time=True)


def process_claim(post: Comment, cfg: Config, first_time=False) -> None:
    """
    Process a claim request.

    This function sends a reply depending on the response from Blossom and
    creates an user when this is the first time a user uses the bot.
    """
    submission = post.submission
    if submission.author.name not in __BOT_NAMES__:
        log.debug("Received 'claim' on post we do not own. Ignoring.")
        return

    response = cfg.blossom.get_submission(reddit_id=submission.fullname)
    if response.status != BlossomStatus.ok:
        # If we are here, this means that the current submission is not yet in Blossom.
        # TODO: Create the Submission in Blossom and try this method again.
        raise Exception("The post is not present in Blossom.")

    response = cfg.blossom.claim_submission(
        submission_id=response.data["id"], username=post.author.name
    )
    if response.status == BlossomStatus.ok:
        message = i18n["responses"]["claim"]["first_claim_success" if first_time else "success"]
        flair_post(submission, flair.in_progress)
        log.info(f'Claim on Submission {submission.fullname} by {post.author} successful.')
    elif response.status == BlossomStatus.missing_prerequisite:
        message = i18n["responses"]["general"]["coc_not_accepted"].format(get_wiki_page("codeofconduct", cfg))
    elif response.status == BlossomStatus.not_found:
        message = i18n["responses"]["general"]["coc_not_accepted"].format(get_wiki_page("codeofconduct", cfg))
        cfg.blossom.create_user(username=post.author.name)
    else:
        message = i18n["responses"]["claim"]["already_claimed"]
    send_reddit_reply(post, _(message))


def process_done(post: Comment, cfg: Config, override=False, alt_text_trigger=False) -> None:
    """
    Handles comments where the user says they've completed a post.
    Also includes a basic decision tree to enable verification of
    the posts to try and make sure they actually posted a
    transcription.

    :param post: the Comment object which contains the string 'done'.
    :param cfg: the global config object.
    :param override: A parameter that can only come from process_override()
        and skips the validation check.
    :param alt_text_trigger: a trigger that adds an extra piece of text onto
        the response. Just something to help ease the number of
        false-positives.
    :return: None.
    """

    top_parent = get_parent_post_id(post, cfg.r)

    done_cannot_find_transcript = i18n['responses']['done']['cannot_find_transcript']
    done_completed_transcript = i18n['responses']['done']['completed_transcript']
    done_still_unclaimed = i18n['responses']['done']['still_unclaimed']

    # WAIT! Do we actually own this post?
    if top_parent.author.name not in __BOT_NAMES__:
        log.info('Received `done` on post we do not own. Ignoring.')
        return

    try:
        if flair.unclaimed in top_parent.link_flair_text:
            post.reply(_(done_still_unclaimed))
        elif top_parent.link_flair_text == flair.in_progress:
            if not override and not verified_posted_transcript(post, cfg):
                # we need to double-check these things to keep people
                # from gaming the system
                log.info(f'Post {top_parent.fullname} does not appear to have a post by claimant {post.author}. Hrm... ')
                # noinspection PyUnresolvedReferences
                try:
                    post.reply(_(done_cannot_find_transcript))
                except ClientException as e:
                    # We've run into an issue where someone has commented and
                    # then deleted the comment between when the bot pulls mail
                    # and when it processes comments. This should catch that.
                    # Possibly should look into subclassing praw.Comment.reply
                    # to include some basic error handling of this so that
                    # we can fix it throughout the application.
                    log.warning(e)
                return

            # Control flow:
            # If we have an override, we end up here to complete.
            # If there is no override, we go into the validation above.
            # If the validation fails, post the apology and return.
            # If the validation succeeds, come down here.

            if override:
                log.info('Moderator override starting!')
            # noinspection PyUnresolvedReferences
            try:
                if alt_text_trigger:
                    post.reply(_(
                        'I think you meant `done`, so here we go!\n\n'
                        f'{done_completed_transcript}'
                    ))
                else:
                    post.reply(_(done_completed_transcript))
                update_user_flair(post, cfg)
                current_post_count = int(cfg.redis.get("total_completed").decode())
                log.info(
                    f'Post {top_parent.fullname} completed by {post.author} -'
                    f' post number {str(current_post_count + 1)}!'
                )
                # get that information saved for the user
                author = User(str(post.author), redis_conn=cfg.redis)
                author.list_update('posts_completed', clean_id(post.fullname))
                author.save()

            except ClientException:
                # If the butt deleted their comment and we're already this
                # far into validation, just mark it as done. Clearly they
                # already passed.
                log.info(f'Attempted to mark post {top_parent.fullname} as done... hit ClientException.')
            flair_post(top_parent, flair.completed)

            cfg.redis.incr('total_completed', amount=1)

    except APIException as e:
        if e.error_type == 'DELETED_COMMENT':
            log.info(f'Comment attempting to mark ID {top_parent.fullname} as done has been deleted')
            return
        raise  # Re-raise exception if not


def process_unclaim(post: Comment, cfg: Config) -> None:
    """
    Process an unclaim request.

    Note that this function also checks whether a post should be removed and
    does so when required.
    """
    submission = post.submission
    if submission.author.name not in __BOT_NAMES__:
        log.debug("Received 'unclaim' on post we do not own. Ignoring.")
        return

    response = cfg.blossom.get_submission(reddit_id=submission.fullname)
    if response.status != BlossomStatus.ok:
        # If we are here, this means that the current submission is not yet in Blossom.
        # TODO: Create the Submission in Blossom and try this method again.
        raise Exception(f"The Submission {submission.fullname} is not present in Blossom.")

    blossom_submission = response.data
    response = cfg.blossom.unclaim(
        submission_id=blossom_submission["id"], username=post.author.name
    )
    unclaim_messages = i18n["responses"]["unclaim"]
    if response.status == BlossomStatus.ok:
        message = unclaim_messages["success"]
        flair_post(submission, flair.unclaimed)
        removed, reported = remove_if_required(submission, blossom_submission["id"], cfg)
        if removed:
            # Select the message based on whether the post was reported or not.
            message = i18n[
                "success_with_report" if reported else "success_without_report"
            ]
    elif response.status == BlossomStatus.not_found:
        message = i18n["responses"]["general"]["coc_not_accepted"].format(
            get_wiki_page("codeofconduct", cfg)
        )
        cfg.blossom.create_user(post.author.name)
    elif response.status == BlossomStatus.other_user:
        message = unclaim_messages["claimed_other_user"]
    elif response.status == BlossomStatus.already_completed:
        message = unclaim_messages["post_already_completed"]
    else:
        message = unclaim_messages["still_unclaimed"]
    send_reddit_reply(post, _(message))


def process_thanks(post: Comment, cfg: Config) -> None:
    thumbs_up_gifs = i18n['urls']['thumbs_up_gifs']
    youre_welcome = i18n['responses']['general']['youre_welcome']
    try:
        post.reply(_(youre_welcome.format(random.choice(thumbs_up_gifs))))
    except APIException as e:
        if e.error_type == 'DELETED_COMMENT':
            log.debug('Comment requiring thanks was deleted')
            return
        raise


def process_wrong_post_location(post: Comment, cfg: Config) -> None:
    transcript_on_tor_post = i18n['responses']['general']['transcript_on_tor_post']
    try:
        post.reply(_(transcript_on_tor_post))
    except APIException:
        log.debug('Something went wrong with asking about a misplaced post; ignoring.')


def process_message(message: Message, cfg: Config) -> None:
    dm_subject = i18n['responses']['direct_message']['dm_subject']
    dm_body = i18n['responses']['direct_message']['dm_body']

    author = message.author
    username = author.name if author else None

    author.message(dm_subject, dm_body)

    if username:
        send_to_modchat(
            f'DM from <{i18n["urls"]["reddit_url"].format("/u/" + username)}|u/{username}> -- '
            f'*{message.subject}*:\n{message.body}', cfg
        )
        log.info(f'Received DM from {username}. \n Subject: {message.subject}\n\nBody: {message.body}')
    else:
        send_to_modchat(
            f'DM with no author -- '
            f'*{message.subject}*:\n{message.body}', cfg
        )
        log.info(f'Received DM with no author. \n Subject: {message.subject}\n\nBody: {message.body}')
