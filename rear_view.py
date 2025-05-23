import os
import cv2
import numpy as np
import tqdm
import argparse
import time
import stitch_utils
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D

from scipy.ndimage import uniform_filter
from scipy.ndimage import median_filter

from multiband import multi_band_blending

# from cylinder import cylinder

# W = 960
# H = 540
W = 720
H = 480

mesh_row_count = 10
mesh_col_count = 16
feature_ellipse_row_count = 6
feature_ellipse_col_count = 10

frame_idx = 0

def measure_performance(method):
    def timed(*args, **kwargs):
        start_time = time.time()
        result = method(*args, **kwargs)
        end_time = time.time()
        print(method.__name__+' has taken: '+str(end_time-start_time)+' sec')
        return result
    return timed

# @measure_performance
def seamcut(src, dst):

    import maxflow
    from energy import get_energy_map
    img_pixel1,img_pixel2,left,right,up,down = get_energy_map(src, dst)

    g = maxflow.GraphFloat()
    img_pixel1 = img_pixel1.astype(float)
    img_pixel1 = img_pixel1*1e10
    img_pixel2 = img_pixel2.astype(float)
    img_pixel2 = img_pixel2*1e10
    nodeids = g.add_grid_nodes(img_pixel1.shape)
    # print(img_pixel1.shape)
    g.add_grid_tedges(nodeids,img_pixel1,img_pixel2)
    structure_left = np.array([[0,0,0],
                            [0,0,1],
                            [0,0,0]])
    g.add_grid_edges(nodeids,weights=left,structure=structure_left,symmetric=False)
    structure_right = np.array([[0,0,0],
                            [1,0,0],
                            [0,0,0]])
    g.add_grid_edges(nodeids,weights=right,structure=structure_right,symmetric=False)
    structure_up = np.array([[0,0,0],
                            [0,0,0],
                            [0,1,0]])
    g.add_grid_edges(nodeids,weights=up,structure=structure_up,symmetric=False)
    structure_down = np.array([[0,1,0],
                            [0,0,0],
                            [0,0,0]])
    g.add_grid_edges(nodeids,weights=down,structure=structure_down,symmetric=False)
    g.maxflow()
    sgm = g.get_grid_segments(nodeids)

    # The labels should be 1 where sgm is False and 0 otherwise.
    img2 = np.int_(np.logical_not(sgm))
    src_mask = img2.astype(np.uint8)
    dst_mask = np.logical_not(img2).astype(np.uint8)
    src_mask = np.stack((src_mask,src_mask,src_mask),axis=-1)
    dst_mask = np.stack((dst_mask,dst_mask,dst_mask),axis=-1)

    src = src*src_mask
    dst = dst*dst_mask

    result = src+dst
    return result

def plot_motionfield(motion_field_origin, motion_field_filtered):
  
    stabilized_mediafiltered_motion_mesh_x = motion_field_filtered[:, :, 0]
    stabilized_mediafiltered_motion_mesh_y = motion_field_filtered[:, :, 1]
    
    stabilized_motion_mesh_unfiltered_x = motion_field_origin[:, :, 0]
    stabilized_motion_mesh_unfiltered_y = motion_field_origin[:, :, 1]
    
    fig = plt.figure()

    x = np.arange(0,1280+64,64)
    y = np.arange(0,720+60,60)
    x, y = np.meshgrid(x, y)

    ax1 = fig.add_subplot(221, projection="3d")
    surf = ax1.plot_surface(x, y, stabilized_motion_mesh_unfiltered_x, rstride=1, cstride=1, alpha=0.9, cmap=plt.cm.coolwarm)
    ax1.set_zlim(-400, -100)
    ax1.set_xlabel("W")
    ax1.set_ylabel("H")
    ax1.set_zlabel("pixel")
    # ax1.set_title("stabilized_unfiltered_motion_mesh_x")
    ax1.contourf(x, y, stabilized_mediafiltered_motion_mesh_y, zdir='z',offset=-400)

    ax2 = fig.add_subplot(222, projection="3d")
    surf = ax2.plot_surface(x, y, stabilized_mediafiltered_motion_mesh_x, rstride=1, cstride=1, alpha=0.9, cmap=plt.cm.coolwarm)
    ax2.set_zlim(-400, -100)
    cax1 = fig.add_axes([ax2.get_position().x1+0.05, ax2.get_position().y0, 0.02, ax2.get_position().height])
    fig.colorbar(surf, cax=cax1)
    ax2.set_xlabel("W")
    ax2.set_ylabel("H")
    ax2.set_zlabel("pixel")
    # ax2.set_title("stabilized_mediafiltered_motion_mesh_x")
    ax2.contourf(x, y, stabilized_mediafiltered_motion_mesh_y, zdir='z',offset=-400)
    
    ax3 = fig.add_subplot(223, projection="3d")
    surf = ax3.plot_surface(x, y, stabilized_motion_mesh_unfiltered_y, rstride=1, cstride=1, alpha=0.9, cmap=plt.cm.coolwarm)
    ax3.set_zlim(-100, 100)
    ax3.set_xlabel("W")
    ax3.set_ylabel("H")
    ax3.set_zlabel("pixel")
    # ax3.set_title("stabilized_unfiltered_motion_mesh_y")
    ax3.contourf(x, y, stabilized_motion_mesh_unfiltered_y, zdir='z',offset=-100)
    
    ax4 = fig.add_subplot(224, projection="3d")
    surf = ax4.plot_surface(x, y, stabilized_mediafiltered_motion_mesh_y, rstride=1, cstride=1, alpha=0.9, cmap=plt.cm.coolwarm)
    ax4.set_zlim(-100, 100)
    cax2 = fig.add_axes([ax4.get_position().x1+0.05, ax4.get_position().y0, 0.02, ax4.get_position().height])
    fig.colorbar(surf, cax=cax2)
    ax4.set_xlabel("W")
    ax4.set_ylabel("H")
    ax4.set_zlabel("pixel")
    # ax4.set_title("stabilized_mediafiltered_motion_mesh_y")
    ax4.contourf(x, y, stabilized_mediafiltered_motion_mesh_y, zdir='z',offset=-100)
    
    plt.show()

def motion_field_filter(left_velocity, right_velocity):
    # 中值滤波器去噪
    left_velocity = median_filter(left_velocity, size=3)
    right_velocity = median_filter(right_velocity, size=3)

    # 运动场的平滑过程 调试中
    print(np.median(left_velocity[:, 14, 0]))
    print(np.median(right_velocity[:, 2, 0]))
    O = int((- np.ceil(np.median(left_velocity[:, 14, 0])) + np.floor(np.median(right_velocity[:, 2, 0]))) // 2)
    print(O)
    O_l = -int(np.ceil(np.median(left_velocity[:, 14, 0])))
    print(O_l)
    O_r = int(np.floor(np.median(right_velocity[:, 2, 0])))

    # 边缘的运动场平滑 根据平移量置固定值
    vertex_motion_x_l = left_velocity[:, :16, 0]
    vertex_motion_y_l = left_velocity[:, :16, 1]

    vertex_motion_x_r = right_velocity[:, -16:, 0]
    vertex_motion_y_r = right_velocity[:, -16:, 1]

    vertex_motion_y_l[:, :11] = 0
    vertex_motion_x_l[:, :11] = -O_l
    # # vertex_motion_x_l[:, 1] = -O 
    # vertex_motion_x_l[:, 2] = -O - 15

    vertex_motion_y_r[:, -11:] = 0
    vertex_motion_x_r[:, -11:] = O_r
    # vertex_motion_x_r[:, -2] = O 
    # vertex_motion_x_r[:, -3] = O + 15

    # 均值滤波器
    vertex_motion_x_l_filter = uniform_filter(vertex_motion_x_l, size=5)
    vertex_motion_y_l_filter = uniform_filter(vertex_motion_y_l, size=5)

    vertex_motion_x_r_filter = uniform_filter(vertex_motion_x_r, size=5)
    vertex_motion_y_r_filter = uniform_filter(vertex_motion_y_r, size=5)

    # vertex_motion_x_l_filter[:, :5] = -O
    # vertex_motion_x_r_filter[:, -5:] = O

    # vertex_motion_l_no = np.dstack((vertex_motion_x_l_filter, vertex_motion_y_l_filter))
    # left_velocity[:, :12, :] = vertex_motion_l_no

    # vertex_motion_r_no = np.dstack((vertex_motion_x_r_filter, vertex_motion_y_r_filter))
    # right_velocity[:, -12:, :] = vertex_motion_r_no

    vertex_motion_l_no = np.dstack((vertex_motion_x_l_filter, vertex_motion_y_l_filter))
    # vertex_motion_l_no = np.dstack((vertex_motion_x_l_filter, vertex_motion_y_l))
    left_velocity[:, :16, :] = vertex_motion_l_no

    vertex_motion_r_no = np.dstack((vertex_motion_x_r_filter, vertex_motion_y_r_filter))
    # vertex_motion_r_no = np.dstack((vertex_motion_x_r_filter, vertex_motion_y_r))
    right_velocity[:, -16:, :] = vertex_motion_r_no

    # vertex_motion_y_l[:, :10] = 0
    # vertex_motion_x_l[:, :10] = -O_l

    # vertex_motion_y_r[:, -10:] = 0
    # vertex_motion_x_r[:, -10:] = O_r

    return left_velocity, right_velocity, O_l, O_r, O

if __name__=='__main__':
    
    # 从视频流中读取帧
    ap = argparse.ArgumentParser()
    ap.add_argument("-ll", "--left_left", type=str, default="data/video6.mp4", help="path to the left video")
    ap.add_argument("-l", "--left", type=str, default="data/video5.mp4", help="path to the left video")
    ap.add_argument("-m", "--mid", type=str, default="data/video4.mp4", help="path to the mid video")
    ap.add_argument("-r", "--right", type=str, default="data/video3.mp4", help="path to the right video")
    ap.add_argument("-rr", "--right_right", type=str, default="data/video2.mp4", help="path to the right video")
    args = vars(ap.parse_args())

    # 读取视频
    vs = cv2.VideoCapture(args["left_left"])
    num_frames = np.int32(vs.get(cv2.CAP_PROP_FRAME_COUNT))
    with tqdm.trange(num_frames) as t:
        t.set_description(f'Reading video from <{args["left_left"]}>')
        lleft_frames = []
        for frame_index in t:
            success, pixels = vs.read()
            if success:
                # 规范分辨率
                unstabilized_frame = cv2.resize(pixels, (W, H))
                # unstabilized_frame = cylinder(pixels, W, H)
            else:
                print('capture error')
                exit()
            if unstabilized_frame is None:
                raise IOError(
                    f'Video at <{args["left_left"]}> did not have frame {frame_index} of '
                    f'{num_frames} (indexed from 0).'
                )
            lleft_frames.append(unstabilized_frame)
    vs.release()

    vs = cv2.VideoCapture(args["left"])
    num_frames = np.int32(vs.get(cv2.CAP_PROP_FRAME_COUNT))
    with tqdm.trange(num_frames) as t:
        t.set_description(f'Reading video from <{args["left"]}>')
        left_frames = []
        for frame_index in t:
            success, pixels = vs.read()
            if success:
                # 规范分辨率
                unstabilized_frame = cv2.resize(pixels, (W, H))
                # unstabilized_frame = cylinder(pixels, W, H)
            else:
                print('capture error')
                exit()
            if unstabilized_frame is None:
                raise IOError(
                    f'Video at <{args["left"]}> did not have frame {frame_index} of '
                    f'{num_frames} (indexed from 0).'
                )
            left_frames.append(unstabilized_frame)
    vs.release()

    vs = cv2.VideoCapture(args["mid"])
    num_frames = np.int32(vs.get(cv2.CAP_PROP_FRAME_COUNT))
    with tqdm.trange(num_frames) as t:
        t.set_description(f'Reading video from <{args["mid"]}>')
        mid_frames = []
        for frame_index in t:
            success, pixels = vs.read()
            if success:
                # 规范分辨率
                unstabilized_frame = cv2.resize(pixels, (W, H))
                # unstabilized_frame = cylinder(pixels, W, H)
            else:
                print('capture error')
                exit()
            if unstabilized_frame is None:
                raise IOError(
                    f'Video at <{args["mid"]}> did not have frame {frame_index} of '
                    f'{num_frames} (indexed from 0).'
                )
            mid_frames.append(unstabilized_frame)
    vs.release()

    vs = cv2.VideoCapture(args["right"])
    num_frames = np.int32(vs.get(cv2.CAP_PROP_FRAME_COUNT))
    with tqdm.trange(num_frames) as t:
        t.set_description(f'Reading video from <{args["right"]}>')
        right_frames = []
        for frame_index in t:
            success, pixels = vs.read()
            if success:
                # 规范分辨率
                unstabilized_frame = cv2.resize(pixels, (W, H))
                # unstabilized_frame = cylinder(pixels, W, H)
            else:
                print('capture error')
                exit()
            if unstabilized_frame is None:
                raise IOError(
                    f'Video at <{args["right"]}> did not have frame {frame_index} of '
                    f'{num_frames} (indexed from 0).'
                )
            right_frames.append(unstabilized_frame)
    vs.release()

    vs = cv2.VideoCapture(args["right_right"])
    num_frames = np.int32(vs.get(cv2.CAP_PROP_FRAME_COUNT))
    with tqdm.trange(num_frames) as t:
        t.set_description(f'Reading video from <{args["right_right"]}>')
        rright_frames = []
        for frame_index in t:
            success, pixels = vs.read()
            if success:
                # 规范分辨率
                unstabilized_frame = cv2.resize(pixels, (W, H))
                # unstabilized_frame = cylinder(pixels, W, H)
            else:
                print('capture error')
                exit()
            if unstabilized_frame is None:
                raise IOError(
                    f'Video at <{args["right_right"]}> did not have frame {frame_index} of '
                    f'{num_frames} (indexed from 0).'
                )
            rright_frames.append(unstabilized_frame)
    vs.release()

    lleft_frame_base = lleft_frames[frame_idx]
    # lleft_frame_base = cv2.imread("real_09/final_5/video6/150.jpg")
    # lleft_frame_base_1 = cv2.imread("real_09/final_5/video5/150.jpg")
    left_frame_base = left_frames[frame_idx]
    mid_frame_base = mid_frames[frame_idx]
    right_frame_base = right_frames[frame_idx]
    rright_frame_base = rright_frames[frame_idx]
    # rright_frame_base_1 = cv2.imread("real_09/final_5/video3/180.jpg")
    # rright_frame_base = cv2.imread("real_09/final_5/video2/180.jpg")

    stitcher = stitch_utils.stitch_utils(mesh_row_count=mesh_row_count, mesh_col_count=mesh_col_count, 
                                         feature_ellipse_row_count=feature_ellipse_row_count, feature_ellipse_col_count=feature_ellipse_col_count)

    # 获取匹配特征点 特征点对中点 以及全局单应矩阵
    left_features, right_features, middle_features, early_to_late_homography_l, early_to_late_homography_r = stitcher.get_matched_features_and_homography_for_stitch(lleft_frame_base, left_frame_base) 
    # 获取拼接使用的网格运动场
    left_velocity_1, _ = stitcher.get_velocities_for_stitch(lleft_frame_base, left_features, middle_features, early_to_late_homography_l)
    right_velocity_1, _ = stitcher.get_velocities_for_stitch(lleft_frame_base, right_features, middle_features, early_to_late_homography_r)
   

    # 获取匹配特征点 特征点对中点 以及全局单应矩阵
    left_features, right_features, middle_features, early_to_late_homography_l, early_to_late_homography_r = stitcher.get_matched_features_and_homography_for_stitch(left_frame_base, mid_frame_base) 
    # 获取拼接使用的网格运动场
    left_velocity_2, _ = stitcher.get_velocities_for_stitch(left_frame_base, left_features, middle_features, early_to_late_homography_l)
    right_velocity_2, _ = stitcher.get_velocities_for_stitch(mid_frame_base, right_features, middle_features, early_to_late_homography_r)

    # 获取匹配特征点 特征点对中点 以及全局单应矩阵
    left_features, right_features, middle_features, early_to_late_homography_l, early_to_late_homography_r = stitcher.get_matched_features_and_homography_for_stitch(mid_frame_base, right_frame_base) 
    # 获取拼接使用的网格运动场
    left_velocity_3, _ = stitcher.get_velocities_for_stitch(mid_frame_base, left_features, middle_features, early_to_late_homography_l)
    right_velocity_3, _ = stitcher.get_velocities_for_stitch(right_frame_base, right_features, middle_features, early_to_late_homography_r)
    
    # 获取匹配特征点 特征点对中点 以及全局单应矩阵
    left_features, right_features, middle_features, early_to_late_homography_l, early_to_late_homography_r = stitcher.get_matched_features_and_homography_for_stitch(right_frame_base, rright_frame_base) 
    # 获取拼接使用的网格运动场
    left_velocity_4, _ = stitcher.get_velocities_for_stitch(right_frame_base, left_features, middle_features, early_to_late_homography_l)
    right_velocity_4, _ = stitcher.get_velocities_for_stitch(rright_frame_base, right_features, middle_features, early_to_late_homography_r)
    
    # 获取拼接使用的网格运动场的投影误差
    # err = stitcher.proj_err(W, H, left_features, middle_features, left_velocity)

    ##  原始运动场的可视化部分  ##
    # meshes = stitcher.get_vertex_x_y(frame_width=W, frame_height=H)
    # origin_vertex = np.reshape(meshes, (mesh_row_count + 1, mesh_col_count + 1, 2))
    # for mesh in meshes:
    #     left_frame_mesh = cv2.circle(left_frame_base, (int(mesh[0, 0]), int(mesh[0, 1])), 2, (240, 100, 0), -1)
    #     right_frame_mesh = cv2.circle(mid_frame_base, (int(mesh[0, 0]), int(mesh[0, 1])), 2, (100, 240, 0), -1)
    
    # final_vertex_l = origin_vertex + 0.5 * left_velocity_1
    # final_vertex_r = origin_vertex + 0.5 * right_velocity_1

    # left_frame_mesh_1 = left_frame_mesh.copy()
    # left_frame_mesh_2 = left_frame_mesh.copy()
    # right_frame_mesh_1 = right_frame_mesh.copy()
    # right_frame_mesh_2 = right_frame_mesh.copy()

    # for i in range(mesh_row_count + 1):
    #     for j in range(mesh_col_count + 1):
    #         motion_field_l = cv2.line(left_frame_mesh_1, (int(origin_vertex[i,j,0]), int(origin_vertex[i,j,1])), (int(final_vertex_l[i,j,0]), int(final_vertex_l[i,j,1])), (0,0,255), 1)
    #         motion_field_r = cv2.line(right_frame_mesh_1, (int(origin_vertex[i,j,0]), int(origin_vertex[i,j,1])), (int(final_vertex_r[i,j,0]), int(final_vertex_r[i,j,1])), (0,0,255), 1)


    # 运动场的平滑过程
    left_velocity_1_filter, right_velocity_1_filter, O_l_1, O_r_1, O_1 = motion_field_filter(left_velocity_1, right_velocity_1)
    left_velocity_2_filter, right_velocity_2_filter, O_l_2, O_r_2, O_2 = motion_field_filter(left_velocity_2, right_velocity_2)
    left_velocity_3_filter, right_velocity_3_filter, O_l_3, O_r_3, O_3 = motion_field_filter(left_velocity_3, right_velocity_3)
    left_velocity_4_filter, right_velocity_4_filter, O_l_4, O_r_4, O_4 = motion_field_filter(left_velocity_4, right_velocity_4)

    ##  平滑后运动场的可视化部分  ##
    # final_vertex_l_filter = origin_vertex + 0.5 * left_velocity_1_filter
    # final_vertex_r_filter = origin_vertex + 0.5 * right_velocity_1_filter

    # for i in range(mesh_row_count + 1):
    #     for j in range(mesh_col_count + 1):
    #         motion_field_filter_l = cv2.line(left_frame_mesh_2, (int(origin_vertex[i,j,0]), int(origin_vertex[i,j,1])), (int(final_vertex_l_filter[i,j,0]), int(final_vertex_l_filter[i,j,1])), (0,0,255), 1)
    #         motion_field_filter_r = cv2.line(right_frame_mesh_2, (int(origin_vertex[i,j,0]), int(origin_vertex[i,j,1])), (int(final_vertex_r_filter[i,j,0]), int(final_vertex_r_filter[i,j,1])), (0,0,255), 1)

    # cv2.imshow('motion field of left', motion_field_l)
    # cv2.imshow('motion field filtered of left', motion_field_filter_l)
    # cv2.imshow('motion field of right', motion_field_r)
    # cv2.imshow('motion field filtered of right', motion_field_filter_r)
    # cv2.waitKey(0)


    ## 图片展示 ##
    # # 网格变形
    # img_l_1 = stitcher.get_warped_frames_for_stitch(0, lleft_frame_base, left_velocity_1_filter, O_l_1)
    # img_r_1 = stitcher.get_warped_frames_for_stitch(1, left_frame_base, right_velocity_1_filter, O_r_1)

    # img_l_2 = stitcher.get_warped_frames_for_stitch(0, left_frame_base, left_velocity_2_filter, O_l_2)
    # img_r_2 = stitcher.get_warped_frames_for_stitch(1, mid_frame_base, right_velocity_2_filter, O_r_2)

    # img_l_3 = stitcher.get_warped_frames_for_stitch(0, mid_frame_base, left_velocity_3_filter, O_l_3)
    # img_r_3 = stitcher.get_warped_frames_for_stitch(1, right_frame_base, right_velocity_3_filter, O_r_3)

    # img_l_4 = stitcher.get_warped_frames_for_stitch(0, right_frame_base, left_velocity_4_filter, O_l_4)
    # img_r_4 = stitcher.get_warped_frames_for_stitch(1, rright_frame_base, right_velocity_4_filter, O_r_4)

    # # 缝合线选取
    # l = np.zeros((H, W + 2 * O_1, 3), np.uint8)
    # r = np.zeros((H, W + 2 * O_1, 3), np.uint8)
    # l[:, :W, :] = img_l_1
    # r[:, 2 * O_1:, :] = img_r_1
    # stitched_seam_1 = seamcut(l, r)

    # l = np.zeros((H, W + 2 * O_2, 3), np.uint8)
    # r = np.zeros((H, W + 2 * O_2, 3), np.uint8)
    # l[:, :W, :] = img_l_2
    # r[:, 2 * O_2:, :] = img_r_2
    # stitched_seam_2 = seamcut(l, r)

    # l = np.zeros((H, W + 2 * O_3, 3), np.uint8)
    # r = np.zeros((H, W + 2 * O_3, 3), np.uint8)
    # l[:, :W, :] = img_l_3
    # r[:, 2 * O_3:, :] = img_r_3
    # stitched_seam_3 = seamcut(l, r)

    # l = np.zeros((H, W + 2 * O_4, 3), np.uint8)
    # r = np.zeros((H, W + 2 * O_4, 3), np.uint8)
    # l[:, :W, :] = img_l_4
    # r[:, 2 * O_4:, :] = img_r_4
    # stitched_seam_4 = seamcut(l, r)

    # # 多频段融合
    # flag_half = False
    # mask = None
    # need_mask =True
    # leveln = 5

    # overlap_w = W-2*O_1
    # stitched_band_1 = multi_band_blending(img_l_1, img_r_1, mask, overlap_w, leveln, flag_half, need_mask)

    # overlap_w = W-2*O_2
    # stitched_band_2 = multi_band_blending(img_l_2, img_r_2, mask, overlap_w, leveln, flag_half, need_mask)

    # overlap_w = W-2*O_3
    # stitched_band_3 = multi_band_blending(img_l_3, img_r_3, mask, overlap_w, leveln, flag_half, need_mask)

    # overlap_w = W-2*O_4
    # stitched_band_4 = multi_band_blending(img_l_4, img_r_4, mask, overlap_w, leveln, flag_half, need_mask)

    # rearview = np.concatenate((stitched_seam_1[:, :-W//2+50, :], stitched_seam_2[:, W//2+50:-W//2, :], stitched_seam_3[:, W//2:-W//2, :], stitched_seam_4[:, W//2:, :]), axis=1)
    # rearview_band = np.concatenate((stitched_band_1[:, :-W//2+50, :], stitched_band_2[:, W//2+50:-W//2, :], stitched_band_3[:, W//2:-W//2, :], stitched_band_4[:, W//2:, :]), axis=1)

    # # # 显示结果
    # # # cv2.imshow('warp_left', img_l_1)
    # # # cv2.imshow('warp_right', img_r_1)
    # # # cv2.imshow('left', l)
    # # # cv2.imshow('right', r)
    # # # cv2.imshow('stitched_1', stitched_seam_1)
    # cv2.imshow('stitched_multiband_1', stitched_band_1)
    # # # cv2.imshow('stitched_2', stitched_seam_2)
    # cv2.imshow('stitched_multiband_2', stitched_band_2)
    # cv2.imshow('rearview', rearview)
    # cv2.imshow('rearview_multiband', rearview_band)

    # cv2.waitKey(0)
    # # cv2.imwrite('20240220/res.jpg', stitched)

    O_1 = O_1 + 15
    O_4 = O_4 + 42 

    ## 视频处理 ##
    with tqdm.trange(num_frames) as t:
        t.set_description(f'stitching frames')
        stitched_frames = []
        stitched_frames_multiband = []
        # left_warp = []
        # right_warp = []
        for frame_index in t:
            lleft_frame_ = lleft_frames[frame_index]
            left_frame_ = left_frames[frame_index]
            mid_frame_ = mid_frames[frame_index]
            right_frame_ = right_frames[frame_index]
            rright_frame_ = rright_frames[frame_index]
            # 网格变形
            img_l_1 = stitcher.get_warped_frames_for_stitch(0, lleft_frame_, left_velocity_1_filter, O_l_1)
            img_r_1 = stitcher.get_warped_frames_for_stitch(1, left_frame_, right_velocity_1_filter, O_r_1)

            img_l_2 = stitcher.get_warped_frames_for_stitch(0, left_frame_, left_velocity_2_filter, O_l_2)
            img_r_2 = stitcher.get_warped_frames_for_stitch(1, mid_frame_, right_velocity_2_filter, O_r_2)

            img_l_3 = stitcher.get_warped_frames_for_stitch(0, mid_frame_, left_velocity_3_filter, O_l_3)
            img_r_3 = stitcher.get_warped_frames_for_stitch(1, right_frame_, right_velocity_3_filter, O_r_3)

            img_l_4 = stitcher.get_warped_frames_for_stitch(0, right_frame_, left_velocity_4_filter, O_l_4)
            img_r_4 = stitcher.get_warped_frames_for_stitch(1, rright_frame_, right_velocity_4_filter, O_r_4)
            # left_warp.append(img_l)
            # right_warp.append(img_r) 

            # 缝合线选取
            l = np.zeros((H, W + 2 * O_1, 3), np.uint8)
            r = np.zeros((H, W + 2 * O_1, 3), np.uint8)
            l[:, :W, :] = img_l_1
            r[:, 2 * O_1:, :] = img_r_1
            stitched_seam_1 = seamcut(l, r)

            l = np.zeros((H, W + 2 * O_2, 3), np.uint8)
            r = np.zeros((H, W + 2 * O_2, 3), np.uint8)
            l[:, :W, :] = img_l_2
            r[:, 2 * O_2:, :] = img_r_2
            stitched_seam_2 = seamcut(l, r)

            l = np.zeros((H, W + 2 * O_3, 3), np.uint8)
            r = np.zeros((H, W + 2 * O_3, 3), np.uint8)
            l[:, :W, :] = img_l_3
            r[:, 2 * O_3:, :] = img_r_3
            stitched_seam_3 = seamcut(l, r)

            l = np.zeros((H, W + 2 * O_4, 3), np.uint8)
            r = np.zeros((H, W + 2 * O_4, 3), np.uint8)
            l[:, :W, :] = img_l_4
            r[:, 2 * O_4:, :] = img_r_4
            stitched_seam_4 = seamcut(l, r)

            # 多频段融合
            flag_half = False
            mask = None
            need_mask =True
            leveln = 5

            overlap_w = W-2*O_1
            stitched_band_1 = multi_band_blending(img_l_1, img_r_1, mask, overlap_w, leveln, flag_half, need_mask)

            overlap_w = W-2*O_2
            stitched_band_2 = multi_band_blending(img_l_2, img_r_2, mask, overlap_w, leveln, flag_half, need_mask)

            overlap_w = W-2*O_3
            stitched_band_3 = multi_band_blending(img_l_3, img_r_3, mask, overlap_w, leveln, flag_half, need_mask)

            overlap_w = W-2*O_4
            stitched_band_4 = multi_band_blending(img_l_4, img_r_4, mask, overlap_w, leveln, flag_half, need_mask)

            rearview = np.concatenate((stitched_seam_1[:, :-W//2, :], stitched_seam_2[:, W//2:-W//2 - 2, :], stitched_seam_3[:, W//2:-W//2, :], stitched_seam_4[:, W//2:, :]), axis=1)
            rearview_band = np.concatenate((stitched_band_1[:, :-W//2, :], stitched_band_2[:, W//2:-W//2 - 2, :], stitched_band_3[:, W//2:-W//2, :], stitched_band_4[:, W//2:, :]), axis=1)

            os.makedirs('data/rear/seamcut', exist_ok=True)
            os.makedirs('data/rear/multiband', exist_ok=True)
            cv2.imwrite('data/rear/seamcut/'+'{:0{}d}'.format(frame_index + 0, 3) + '.jpg', rearview)
            cv2.imwrite('data/rear/multiband/'+'{:0{}d}'.format(frame_index + 0, 3) + '.jpg', rearview_band)

            stitched_frames.append(rearview)
            stitched_frames_multiband.append(rearview_band)

    # 保存视频文件
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    fps = 30

    # frame_height, frame_width, _ = left_warp[0].shape
    # video = cv2.VideoWriter('real_09/calib_0_6/09_0_6_4_3_l_warp_c.mp4', fourcc, fps, (frame_width, frame_height))
    # for i in tqdm.trange(num_frames):
    #     video.write(left_warp[i])
    # video.release()
    # video = cv2.VideoWriter('real_09/calib_0_6/09_0_6_4_3_r_warp_c.mp4', fourcc, fps, (frame_width, frame_height))
    # for i in tqdm.trange(num_frames):
    #     video.write(right_warp[i])
    # video.release()

    frame_height, frame_width, _ = stitched_frames[0].shape
    video = cv2.VideoWriter('data/rear/rear_seamcut.mp4', fourcc, fps, (frame_width, frame_height))
    for i in tqdm.trange(num_frames):
        video.write(stitched_frames[i])
    video.release()
    
    frame_height, frame_width, _ = stitched_frames_multiband[0].shape
    video = cv2.VideoWriter('data/rear/rear_multiband.mp4', fourcc, fps, (frame_width, frame_height))
    for i in tqdm.trange(num_frames):
        video.write(stitched_frames_multiband[i])
    video.release()
    print('Write Done!')