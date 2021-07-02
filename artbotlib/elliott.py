from . import util

def image_list(so, advisory_id):
    rc, stdout, stderr = util.cmd_assert(so, f'elliott advisory-images -a {advisory_id}')
    if rc:
        util.please_notify_art_team_of_error(so, stderr)
    else:
        so.snippet(payload=stdout, intro=f"Here's the image list for advisory {advisory_id}",
                   filename=f'{advisory_id}.images.txt')
