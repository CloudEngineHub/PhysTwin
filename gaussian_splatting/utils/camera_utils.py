#
# Copyright (C) 2023, Inria
# GRAPHDECO research group, https://team.inria.fr/graphdeco
# All rights reserved.
#
# This software is free for non-commercial, research and evaluation use 
# under the terms of the LICENSE.md file.
#
# For inquiries contact  george.drettakis@inria.fr
#

from ..scene.cameras import Camera
import numpy as np
from ..utils.graphics_utils import fov2focal
from ..utils.general_utils import PILtoTorch
from PIL import Image
import cv2
import torch

WARNED = False

def loadCam(args, id, cam_info, resolution_scale, is_nerf_synthetic, is_test_dataset):
    # image = Image.open(cam_info.image_path)
    image = cam_info.image

    if cam_info.depth_path != "":
        try:
            if is_nerf_synthetic:
                invdepthmap = cv2.imread(cam_info.depth_path, -1).astype(np.float32) / 512
            else:
                invdepthmap = cv2.imread(cam_info.depth_path, -1).astype(np.float32) / float(2**16)

        except FileNotFoundError:
            print(f"Error: The depth file at path '{cam_info.depth_path}' was not found.")
            raise
        except IOError:
            print(f"Error: Unable to open the image file '{cam_info.depth_path}'. It may be corrupted or an unsupported format.")
            raise
        except Exception as e:
            print(f"An unexpected error occurred when trying to read depth at {cam_info.depth_path}: {e}")
            raise
    else:
        invdepthmap = None
        
    # orig_w, orig_h = image.size
    orig_w, orig_h = cam_info.width, cam_info.height
    if args.resolution in [1, 2, 4, 8]:
        resolution = round(orig_w/(resolution_scale * args.resolution)), round(orig_h/(resolution_scale * args.resolution))
        K = cam_info.K / (resolution_scale * args.resolution)
    else:  # should be a type that converts to float
        if args.resolution == -1:
            if orig_w > 1600:
                global WARNED
                if not WARNED:
                    print("[ INFO ] Encountered quite large input images (>1.6K pixels width), rescaling to 1.6K.\n "
                        "If this is not desired, please explicitly specify '--resolution/-r' as 1")
                    WARNED = True
                global_down = orig_w / 1600
            else:
                global_down = 1
        else:
            global_down = orig_w / args.resolution

        scale = float(global_down) * float(resolution_scale)
        resolution = (int(orig_w / scale), int(orig_h / scale))
        K = cam_info.K / scale

    # resize depth and normal
    depth = None
    normal = None
    if cam_info.depth is not None:
        depth = torch.from_numpy(cam_info.depth).unsqueeze(0).unsqueeze(0)
        depth = torch.nn.functional.interpolate(depth, (resolution[1], resolution[0]), mode='bilinear', align_corners=True)
        depth = depth.squeeze(0).squeeze(0)          # (H, W)
    if cam_info.normal is not None:
        normal = torch.from_numpy(cam_info.normal).permute(2, 0, 1).unsqueeze(0)
        normal = torch.nn.functional.interpolate(normal, (resolution[1], resolution[0]), mode='nearest')
        normal = normal.squeeze(0).permute(1, 2, 0)  # (H, W, 3)

    occ_mask = None
    if cam_info.occ_mask is not None:
        occ_mask = torch.from_numpy(cam_info.occ_mask).unsqueeze(0).unsqueeze(0)
        occ_mask = torch.nn.functional.interpolate(occ_mask, (resolution[1], resolution[0]), mode='nearest')
        occ_mask = occ_mask.squeeze(0).squeeze(0)    # (H, W)
    
    return Camera(resolution, colmap_id=cam_info.uid, R=cam_info.R, T=cam_info.T, 
                  FoVx=cam_info.FovX, FoVy=cam_info.FovY, depth_params=cam_info.depth_params,
                  image=image, invdepthmap=invdepthmap,
                  image_name=cam_info.image_name, uid=id, data_device=args.data_device,
                  train_test_exp=args.train_test_exp, is_test_dataset=is_test_dataset, is_test_view=cam_info.is_test,
                  K=cam_info.K, normal=normal, depth=depth, occ_mask=occ_mask)

def cameraList_from_camInfos(cam_infos, resolution_scale, args, is_nerf_synthetic, is_test_dataset):
    camera_list = []

    for id, c in enumerate(cam_infos):
        camera_list.append(loadCam(args, id, c, resolution_scale, is_nerf_synthetic, is_test_dataset))

    return camera_list

def camera_to_JSON(id, camera : Camera):
    Rt = np.zeros((4, 4))
    Rt[:3, :3] = camera.R.transpose()
    Rt[:3, 3] = camera.T
    Rt[3, 3] = 1.0

    W2C = np.linalg.inv(Rt)
    pos = W2C[:3, 3]
    rot = W2C[:3, :3]
    serializable_array_2d = [x.tolist() for x in rot]
    camera_entry = {
        'id' : id,
        'img_name' : camera.image_name,
        'width' : camera.width,
        'height' : camera.height,
        'position': pos.tolist(),
        'rotation': serializable_array_2d,
        'fy' : fov2focal(camera.FovY, camera.height),
        'fx' : fov2focal(camera.FovX, camera.width)
    }
    return camera_entry