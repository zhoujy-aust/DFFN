import torch
import torch.nn as nn
import math
from torch.nn.parameter import Parameter
# from .common import MeanShift, std, default_conv
from common import MeanShift, std, default_conv
#from IPython import embed
import sys
sys.path.append("..")
from option import args

# python ./src/main.py --model FDIWN --scale 4 --pre_train C:\Project\gitProject\FDIWN\FDIWN_TrainCode\experiment\FDIWNx4\model\model_best.pt --test_only --rgb_range 255 --save_results

def make_model(args, parent=False):
    return MODEL(args)

class Scale(nn.Module):

    def __init__(self, init_value=1e-3):
        super().__init__()
        self.scale = nn.Parameter(torch.FloatTensor([init_value]))

    def forward(self, input):
        return input * self.scale


def activation(act_type, inplace=False, neg_slope=0.05, n_prelu=1):
    act_type = act_type.lower()
    if act_type == 'relu':
        layer = nn.ReLU()
    elif act_type == 'lrelu':
        layer = nn.LeakyReLU(neg_slope)
    elif act_type == 'prelu':
        layer = nn.PReLU(num_parameters=n_prelu, init=neg_slope)
    else:
        raise NotImplementedError('activation layer [{:s}] is not found'.format(act_type))
    return layer
        
class SRBW(nn.Module):
    def __init__(
            self, n_feats, wn=lambda x: torch.nn.utils.weight_norm(x), act=nn.ReLU(True)):
        super(SRBW, self).__init__()
        self.res_scale = Scale(1)
        self.x_scale = Scale(1)
        self.conv = nn.Conv2d(n_feats , n_feats*2 , kernel_size=3, padding=1)
        body = []
        body.append(
            wn(nn.Conv2d(n_feats , n_feats*9//2 , kernel_size=1, padding=0)))
        body.append(act)
        body.append(
            wn(nn.Conv2d(n_feats*9//2, n_feats//1, kernel_size=1, padding=0)))
        body.append(
            wn(nn.Conv2d(n_feats//1, n_feats*2, kernel_size=3, padding=1)))

        self.body = nn.Sequential(*body)
        self.SAlayer = sa_layer(2*n_feats)

    def forward(self, x):
        y = self.res_scale(self.SAlayer(self.body(x))) + self.x_scale(self.conv(x))
        return y

class SRBW1(nn.Module):
    def __init__(
            self, n_feats, wn=lambda x: torch.nn.utils.weight_norm(x), act=nn.ReLU(True)):
        super(SRBW1, self).__init__()
        self.res_scale = Scale(1)
        self.x_scale = Scale(1)
        body = []
        body.append(
            wn(nn.Conv2d(n_feats , n_feats*5//2 , kernel_size=1, padding=0)))
        body.append(act)
        body.append(
            wn(nn.Conv2d(n_feats*5//2, n_feats//2, kernel_size=1, padding=0)))
        body.append(
            wn(nn.Conv2d(n_feats//2, n_feats, kernel_size=3, padding=1)))

        self.body = nn.Sequential(*body)
        self.SAlayer = sa_layer(n_feats)

    def forward(self, x):
        y = self.res_scale(self.SAlayer(self.body(x))) + self.x_scale(x)
        return y

class SRBW2(nn.Module):
    def __init__(
            self, n_feats, wn=lambda x: torch.nn.utils.weight_norm(x), act=nn.ReLU(True)):
        super(SRBW2, self).__init__()
        self.res_scale = Scale(1)
        self.x_scale = Scale(1)
        body = []
        body.append(
            wn(nn.Conv2d(n_feats , n_feats*9//4 , kernel_size=1, padding=0)))
        body.append(act)
        body.append(
            wn(nn.Conv2d(n_feats*9//4, n_feats//2, kernel_size=1, padding=0)))
        body.append(
            wn(nn.Conv2d(n_feats//2, n_feats//2, kernel_size=3, padding=1)))

        self.body = nn.Sequential(*body)
        self.SAlayer = sa_layer(n_feats//2)
        self.conv = nn.Conv2d(n_feats , n_feats//2 , kernel_size=3, padding=1)

    def forward(self, x):
        y = self.res_scale(self.SAlayer(self.body(x))) + self.x_scale(self.conv(x))
        return y
        

class CoffConv(nn.Module):
    def __init__(self, n_feats):
        super(CoffConv, self).__init__()
        self.upper_branch = nn.Sequential(
            nn.AdaptiveAvgPool2d(1),
            nn.Conv2d(n_feats, n_feats // 8, 1, 1, 0),
            nn.ReLU(inplace=True),
            nn.Conv2d(n_feats // 8, n_feats, 1, 1, 0),
            nn.ReLU(inplace=True),
            nn.Sigmoid()
        )

        self.std = std
        self.lower_branch = nn.Sequential(
            nn.Conv2d(n_feats, n_feats // 8, 1, 1, 0),
            nn.ReLU(inplace=True),
            nn.Conv2d(n_feats // 8, n_feats, 1, 1, 0),
            nn.ReLU(inplace=True),
            nn.Sigmoid()
        )

    def forward(self, fea):
        upper = self.upper_branch(fea)
        lower = self.std(fea)
        lower = self.lower_branch(lower)

        out = torch.add(upper, lower) / 2

        return out

class sa_layer(nn.Module):
    """Constructs a Channel Spatial Group module.
    Args:
        k_size: Adaptive selection of kernel size
    """
    def __init__(self, n_feats, groups=6):
        super(sa_layer, self).__init__()
        self.groups = groups
        self.avg_pool = nn.AdaptiveAvgPool2d(1)
        self.cweight = Parameter(torch.zeros(1, n_feats // (2 * groups), 1, 1))
        self.cbias = Parameter(torch.ones(1, n_feats // (2 * groups), 1, 1))
        self.sweight = Parameter(torch.zeros(1, n_feats // (2 * groups), 1, 1))
        self.sbias = Parameter(torch.ones(1, n_feats // (2 * groups), 1, 1))

        self.sigmoid = nn.Sigmoid()
        self.gn = nn.GroupNorm(n_feats // (2 * groups), n_feats // (2 * groups))

    @staticmethod
    def channel_shuffle(x, groups):
        b, c, h, w = x.shape

        x = x.reshape(b, groups, -1, h, w)
        x = x.permute(0, 2, 1, 3, 4)

        # flatten
        x = x.reshape(b, -1, h, w)

        return x

    def forward(self, x):
        b, c, h, w = x.shape

        x = x.reshape(b * self.groups, -1, h, w)
        x_0, x_1 = x.chunk(2, dim=1)

        # channel attention
        xn = self.avg_pool(x_0)
        xn = self.cweight * xn + self.cbias
        xn = x_0 * self.sigmoid(xn)

        # spatial attention
        xs = self.gn(x_1)
        xs = self.sweight * xs + self.sbias
        xs = x_1 * self.sigmoid(xs)

        # concatenate along channel axis
        out = torch.cat([xn, xs], dim=1)
        out = out.reshape(b, -1, h, w)

        out = self.channel_shuffle(out, 2)
        return out
    
class ShuffleBlock(nn.Module):
    def __init__(self, groups):
        super(ShuffleBlock, self).__init__()
        self.groups = groups

    def forward(self, x):
        '''Channel shuffle: [N,C,H,W] -> [N,g,C/g,H,W] -> [N,C/g,g,H,w] -> [N,C,H,W]'''
        N,C,H,W = x.size()
        g = self.groups

        return x.view(N,g,int(C/g),H,W).permute(0,2,1,3,4).contiguous().view(N,C,H,W)

class MY(nn.Module):
    def __init__(self, n_feats, act=nn.ReLU(True)):
        super(MY, self).__init__()

        self.act = activation('lrelu', neg_slope=0.05)
        wn = lambda x: torch.nn.utils.weight_norm(x)
        self.srb1 = SRBW1(n_feats)
        self.srb2 = SRBW1(n_feats)
        self.distilled_channels1 = n_feats // 2
        self.remaining_channels1 = n_feats // 2
        self.distilled_channels2 = n_feats // 2
        self.remaining_channels2 = n_feats // 2
        self.rb1 = SRBW(n_feats//2,  wn=wn, act=act)
        self.rb2 = SRBW(n_feats//2,  wn=wn, act=act)
        self.A1_coffconv = CoffConv(n_feats)
        self.B1_coffconv = CoffConv(n_feats)
        self.A2_coffconv = CoffConv(n_feats)
        self.B2_coffconv = CoffConv(n_feats)
        self.conv_distilled1 = nn.Conv2d(n_feats//2, n_feats, kernel_size=3, stride=1, padding=1, bias=False)
        self.conv_distilled2 = nn.Conv2d(n_feats//2, n_feats, kernel_size=3, stride=1, padding=1, bias=False)
        self.sigmoid1 = nn.Sigmoid()
        self.sigmoid2 = nn.Sigmoid()
        self.sigmoid3 = nn.Sigmoid()
        self.scale_x1 = Scale(1)
        self.scale_x2 = Scale(1)
        self.srb3 = SRBW1(n_feats)
        self.srb4 = SRBW1(n_feats)
        self.fuse1 = SRBW2(n_feats*2)
        self.fuse2 = nn.Conv2d(2*n_feats, n_feats, kernel_size=1, stride=1, padding=0, bias=False, dilation=1)
        self.SAlayer = sa_layer(n_feats)

    def forward(self, x):
        out_a = self.act(self.srb1(x))
        distilled_a1, remaining_a1 = torch.split(out_a, (self.distilled_channels1, self.remaining_channels1), dim=1)
        out_a = self.rb1(remaining_a1)
        A1 = self.A1_coffconv(out_a)
        out_b_1 = A1 * out_a + x
        B1 = self.B1_coffconv(x)
        out_a_1 = B1 * x + out_a

        out_b = self.act(self.srb2(out_b_1))
        distilled_b1, remaining_b1 = torch.split(out_b, (self.distilled_channels2, self.remaining_channels2), dim=1)
        out_b = self.rb2(remaining_b1)
        A2 = self.A2_coffconv(out_a_1)
        out_b_2 = A2 * out_a_1 + out_b
        out_b_2 = out_b_2 * self.sigmoid1(self.conv_distilled1(distilled_b1))
        B2 = self.B2_coffconv(out_b)
        out_a_2 = out_b * B2 + out_a_1
        out_a_2 = out_a_2 * self.sigmoid2(self.conv_distilled2(distilled_a1))

        out_a_out = self.srb3(out_a_2)
        out_b_out = self.srb4(out_b_2)

        out1 = self.fuse1(torch.cat([self.scale_x1(out_a_out), self.scale_x2(out_b_out)], dim=1))
        out2 = self.sigmoid3(self.fuse2(torch.cat([self.scale_x1(out_a_out), self.scale_x2(out_b_out)], dim=1)))
        
        out = out2 * out_b_out
        y1 = out1 + out
        y2 = y1 + x
        out = self.SAlayer(y2)

        return out

class Li(nn.Module):
    def __init__(self, n_feats, bn=False, act=nn.ReLU(True)):
        super(Li, self).__init__()

        self.act = activation('lrelu', neg_slope=0.05)
        wn = lambda x: torch.nn.utils.weight_norm(x)
        self.MY1 = MY(n_feats )
        self.MY2 = MY(n_feats )
        self.MY3 = MY(n_feats )
        self.conv = nn.Conv2d(n_feats , n_feats , kernel_size=3, stride=1, padding=1, bias=False, dilation=1)
        self.conv1 = nn.Conv2d(2*n_feats , n_feats , kernel_size=3, stride=1, padding=1, groups=4, bias=False, dilation=1)
        self.conv2 = nn.Conv2d(2*n_feats , n_feats , kernel_size=3, stride=1, padding=1, groups=4, bias=False, dilation=1)
        self.channel_shuffle1 = ShuffleBlock(groups=4)
        self.channel_shuffle2 = ShuffleBlock(groups=4)
        self.rb1 = SRBW1(n_feats, wn=wn, act=act)
        self.scale_x = Scale(0.5)
        self.scale_res = Scale(0.5)
 
    def forward(self, x):
        out1 = self.MY1(x)
        out1_1 = self.MY2(out1)
        out1_2 = self.conv(out1)
        out2 =out1_1 + out1_2
        out3 = self.MY3(out2)
        
        out_concat1 = self.conv1(self.channel_shuffle1(torch.cat([out1, out1_1], dim=1)))
        out_concat2 = self.conv2(self.channel_shuffle1(torch.cat([out_concat1, out3], dim=1)))
        
        res = self.rb1(x)
        out = self.scale_x(out_concat2+out3) + self.scale_res(res)

        return out

class MODEL(nn.Module):
    def __init__(self, args,conv=default_conv):
        super(MODEL, self).__init__()
        n_feats = args.n_feats
        kernel_size = 3
        n_colors = 3
        out_channels = 3
        upscale_factor = 2
        self.act = activation('lrelu', neg_slope=0.05)
        self.Upsample = nn.Upsample(scale_factor=4,
                                    mode='bilinear', align_corners=False)
        rgb_mean = (0.4488, 0.4371, 0.4040)
        rgb_std = (1.0, 1.0, 1.0)
        self.Sub_mean = MeanShift(255, rgb_mean, rgb_std)
        self.Add_mean = MeanShift(255, rgb_mean, rgb_std, 1)
        self.head = conv(n_colors, 3*n_feats//8 , kernel_size) 
        self.Li1 = Li(3*n_feats//8)
        self.Li2 = Li(3*n_feats//8)
        self.Li3 = Li(3*n_feats//8)
        
        self.conv1 = nn.Conv2d(3*n_feats //8 , n_feats//2, kernel_size=3, stride=1, padding=1, bias=False)
        up_body = []
        up_body.append(default_conv(n_feats//2, out_channels*16, kernel_size=3, bias=True))
        up_body.append(nn.PixelShuffle(4))
        self.UP1 = nn.Sequential(*up_body)
        
        self.conv2 = conv(n_colors, 8*n_feats//16 , kernel_size)
        up_body = []
        up_body.append(default_conv(8*n_feats//16,out_channels*16, kernel_size=3, bias=True))
        up_body.append(nn.PixelShuffle(4))
        self.UP2 = nn.Sequential(*up_body)
        

    def forward(self, x):
        y_input1 = self.Sub_mean(x)
        y_input = self.head(y_input1)  # 32
        y_input = self.Li1(y_input)
        
        y_input_up1 = self.Li1(y_input)
        y_input_down1 = y_input + y_input_up1
        y_input_up2 = self.Li2(y_input_down1)
        y_input_down2 = y_input_down1 + y_input_up2
        y_input_up3 = self.Li3(y_input_down2)
        y_input_down3 = y_input_down2 + y_input_up3
        y_input_up4 = self.Li2(y_input_down3)
        y_input_down4 = y_input_down3 + y_input_up4
        
        y_input_down5 = self.Li3(y_input_down4)

        y_final = y_input + y_input_up1 + y_input_up2 + y_input_up3 + y_input_up4 + y_input_down5
        y1 = self.UP1(self.conv1(y_final))
        y2 = self.UP2(self.conv2(y_input1))
        y = y1 + y2
        output = self.Add_mean(y)

        return output

if __name__ == '__main__':
    # import cv2

    # img = cv2.imread('001.jpg')
 
    # model = create_model()
 
    # img_batch = np.expand_dims(img, axis=0)
    # conv_img = model.predict(img_batch)  # conv_img 卷积结果
 
    # visualize_feature_map(conv_img)

    from torchsummary import summary
    from torchinfo import summary
    from thop import profile
    from thop import clever_format
    device = torch.device('cuda')
    # checkpoint = utility.checkpoint(args)
    # upscale = 4
    # window_size = 8
    # height = (1024 // upscale // window_size + 1) * window_size
    # width = (720 // upscale // window_size + 1) * window_size
    model = MODEL(args)
    input = torch.randn(16, 3, 64, 64)
    input = input.to(device)
    model = model.to(device)
    # summary(model,(3,40,40),batch_size=1,device="cuda")  #torchsummary
    # print(model)
    summary(model,(16,3,64,64),device="cuda")  #torchinfo

    print('parameters_count:',sum(p.numel() for p in model.parameters() if p.requires_grad))
    
    # flops, params = profile(model, inputs=(input, ))
    # print(flops, params)
    # flops, params = clever_format([flops, params], "%.3f")
    # print(flops, params)