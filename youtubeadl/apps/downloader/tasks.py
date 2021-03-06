from __future__ import absolute_import

import os
import shutil
import subprocess
import uuid

from django.conf import settings

from celery import shared_task

from youtubeadl.apps.downloader.models import Video, ActivityLog
from youtubeadl.apps.downloader.utils import create_filename, get_video_info


@shared_task(time_limit=900)
def convert(url, client_ip=None):
    """
    Convert the YouTube video to MP3 audio.

    Steps:
        1. Get the video's information to make sure the provided url is valid.
        2. If info is returned and the duration is no more than
           MAX_DURATION_SECONDS, log the request and start the conversion.
        3. Return the download link if conversion completes successfully.
    """
    result = None
    duration = None

    info = get_video_info(url)
    if info:
        duration = info.get('duration')

    if info and duration and duration <= settings.MAX_DURATION_SECONDS:
        youtube_id = info['id']
        title = info['title']

        audio_filename = create_filename(info['title'])

        video, created = Video.objects.get_or_create(youtube_id=youtube_id)
        video.url = url
        video.title = title
        video.duration = duration
        video.save()

        ActivityLog.objects.create(
            video=video,
            client_ip=client_ip,
            action=ActivityLog.CONVERT,
        )

        result = {
            'youtube_id': youtube_id,
            'title': title
        }

        # Simply return the filename and update the video object if the file
        # already exists, otherwise, start the conversion.
        output_filepath = os.path.join(settings.MEDIA_ROOT, audio_filename)
        if os.path.exists(output_filepath):
            result['filename'] = audio_filename

            # Update the video object.
            video.audio_filename = audio_filename
            video.audio_filesize = os.path.getsize(output_filepath)
            video.save()
        else:
            conversion_result = start_conversion(url, audio_filename, video)

            # If extraction result is 0, extraction is successful.
            if conversion_result == 0:
                result['filename'] = audio_filename

    return result


def start_conversion(url, audio_filename, video):
    # We're creating a temporary file in case multiple workers are in the
    # process of converting the same video.
    temp_filepath = os.path.join(settings.MEDIA_ROOT,
                                 '{0}_{1}'.format(uuid.uuid4(), audio_filename))
    output_filepath = os.path.join(settings.MEDIA_ROOT, audio_filename)

    result = subprocess.check_call([
        'youtube-dl',
        '--no-playlist',
        '--extract-audio',
        '--audio-format', 'mp3',
        '--output', temp_filepath,
        '--cache-dir', '/tmp/youtube-dl',
        url,
    ])

    # Status code 0 is successful.
    if result == 0:
        # Move the temporary file to the proper location.
        shutil.move(temp_filepath, output_filepath)

        # Update the video object.
        video.audio_filename = audio_filename
        video.audio_filesize = os.path.getsize(output_filepath)
        video.save()

    return result
