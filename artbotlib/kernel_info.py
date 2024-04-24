import asyncio
import logging

from artbotlib import constants, brew_list, util, rhcos
from artbotlib import buildinfo


class KernelInfo:
    def __init__(self, so, release_img, arch):
        self.logger = logging.getLogger(__class__.__name__)
        self.so = so
        self.release_img = release_img
        self.arch = arch

    async def run(self):
        self.so.say(f'Gathering image info for `{self.release_img}`...')
        self.logger.info('Gathering image info for %s with arch %s',
                         self.release_img, self.arch)

        results = await asyncio.gather(
            *[
                self.non_rhcos_kernel_info('driver-toolkit'),
                self.non_rhcos_kernel_info('ironic-machine-os-downloader'),
                self.rhcos_kernel_info()
            ], return_exceptions=False)

        output = []
        # If the result entry is None, something happened
        # Skip it, assuming the user has already been notified abut errors
        for entry in filter(lambda x: x, results):
            output.append(f'Kernel info for `{entry["name"]}` {entry["pullspec"]}:')
            output.append('```')
            output.extend(entry['rpms'])
            output.append('```')

        self.so.say('\n'.join(output))

    async def non_rhcos_kernel_info(self, image):
        # Get image build for provided release image
        build_info, pullspec, _ = await buildinfo.get_image_info(self.so, image, self.release_img)
        if not build_info:
            # Release wasn't found. Already notified on Slack
            return None

        labels = build_info["config"]["config"]["Labels"]

        try:
            name = labels["com.redhat.component"]
            version = labels["version"]
            release = labels["release"]
        except KeyError:
            self.logger.error('Not all needed labels were found: %s', labels)
            return None

        build_nvr = f"{name}-{version}-{release}"
        self.logger.info('Found build nvr: %s', build_nvr)

        # Get rpms version
        matched = brew_list.list_specific_rpms_for_image(['kernel-core', 'kernel-rt'], build_nvr)
        return {
            'name': image,
            'rpms': list(matched),
            'pullspec': pullspec
        }

    async def rhcos_kernel_info(self):
        rpms = []
        pullspec, _ = buildinfo.get_img_pullspec(self.release_img)
        rhcos_build_id = await rhcos.get_rhcos_build_id_from_pullspec(pullspec)
        if not rhcos_build_id:
            self.logger.error('Failed to fetch RHCOS info for %s', self.release_img)
            self.so.say(f'Failed to fetch RHCOS info for {self.release_img}')
            return None

        # Fetch RHCOS build metadata
        rhcos_build_info = rhcos.RHCOSBuildInfo(ocp_version=util.ocp_version_from_release_img(self.release_img))
        metadata = rhcos_build_info.build_metadata(
            rhcos_build_id, constants.RC_ARCH_TO_RHCOS_ARCH[self.arch])
        pkg_list = metadata['rpmostree.rpmdb.pkglist']
        kernel_core = [pkg for pkg in pkg_list if 'kernel-core' in pkg][0]
        rpms.append(f'kernel-core.{".".join(kernel_core[2:])}')

        return {
            'name': 'rhcos',
            'rpms': rpms,
            'pullspec': pullspec
        }


def kernel_info(so, release_img, arch):
    # Validate arch parameter
    arch = 'amd64' if not arch else arch
    valid_arches = constants.RC_ARCH_TO_RHCOS_ARCH.keys()
    if arch not in valid_arches:
        so.say(f'Arch {arch} is not valid: please choose one in {", ".join(valid_arches)}')
        return

    asyncio.new_event_loop().run_until_complete(
        KernelInfo(so, release_img, arch).run()
    )
