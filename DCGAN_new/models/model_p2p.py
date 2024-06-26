import torch
from torch import nn
import numpy as np
import torch.nn.functional as F
import tools

class ContractingBlock(nn.Module):
    '''
    ContractingBlock Class
    Performs two convolutions followed by a max pool operation.
    Values:
        input_channels: the number of channels to expect from a given input
    '''
    def     __init__(self, input_channels, use_dropout=False, use_bn=True,s1=2,k1=2):
        super(ContractingBlock, self).__init__()
        #self.conv1 = nn.Conv2d(input_channels, input_channels * 2, kernel_size=3, padding=1)
        self.conv1 = nn.Conv3d(input_channels, input_channels * 2, kernel_size=3, padding=1)
        #self.conv2 = nn.Conv2d(input_channels * 2, input_channels * 2, kernel_size=3, padding=1)
        self.conv2 = nn.Conv3d(input_channels * 2, input_channels * 2, kernel_size=3, padding=1)
        self.activation = nn.LeakyReLU(0.2)
        #self.maxpool = nn.MaxPool2d(kernel_size=2, stride=2)
        self.maxpool = nn.MaxPool3d(kernel_size=k1, stride=s1)
        if use_bn:
            #self.batchnorm = nn.BatchNorm2d(input_channels * 2)
            # self.batchnorm = nn.BatchNorm3d(input_channels * 2)
            self.instancenorm=nn.InstanceNorm3d(input_channels*2)
        self.use_bn = use_bn
        if use_dropout:
            self.dropout = nn.Dropout()
        self.use_dropout = use_dropout

    def forward(self, x):
        '''
        Function for completing a forward pass of ContractingBlock:
        Given an image tensor, completes a contracting block and returns the transformed tensor.
        Parameters:
            x: image tensor of shape (batch size, channels, height, width)
        '''
        x = self.conv1(x)
        if self.use_bn:
            x = self.instancenorm(x)
        if self.use_dropout:
            x = self.dropout(x)
        x = self.activation(x)
        x = self.conv2(x)
        if self.use_bn:
            x = self.instancenorm(x)
        if self.use_dropout:
            x = self.dropout(x)
        x = self.activation(x)
        x = self.maxpool(x)
        return x

class ExpandingBlock(nn.Module):
    '''
    ExpandingBlock Class:
    Performs an upsampling, a convolution, a concatenation of its two inputs,
    followed by two more convolutions with optional dropout
    Values:
        input_channels: the number of channels to expect from a given input
    '''
    def __init__(self, input_channels, use_dropout=False, use_bn=True,s1=2):
        super(ExpandingBlock, self).__init__()
        self.upsample = nn.Upsample(scale_factor=s1, mode='trilinear', align_corners=True)
        # self.conv1 = nn.Conv2d(input_channels, input_channels // 2, kernel_size=2)
        # self.conv2 = nn.Conv2d(input_channels, input_channels // 2, kernel_size=3, padding=1)
        # self.conv3 = nn.Conv2d(input_channels // 2, input_channels // 2, kernel_size=2, padding=1)
        self.conv1 = nn.Conv3d(input_channels, input_channels // 2, kernel_size=2)
        self.conv2 = nn.Conv3d(input_channels, input_channels // 2, kernel_size=3, padding=1)
        self.conv3 = nn.Conv3d(input_channels // 2, input_channels // 2, kernel_size=2, padding=1)
        if use_bn:
            # self.batchnorm = nn.BatchNorm2d(input_channels // 2)
            self.batchnorm = nn.BatchNorm3d(input_channels // 2)
            self.instancenorm=nn.InstanceNorm3d(input_channels//2)
        self.use_bn = use_bn
        self.activation = nn.ReLU()
        if use_dropout:
            self.dropout = nn.Dropout()
        self.use_dropout = use_dropout

    def forward(self, x, skip_con_x):
        '''
        Function for completing a forward pass of ExpandingBlock:
        Given an image tensor, completes an expanding block and returns the transformed tensor.
        Parameters:
            x: image tensor of shape (batch size, channels, height, width)
            skip_con_x: the image tensor from the contracting path (from the opposing block of x)
                    for the skip connection
        '''
        # print(x.shape)
        #[2048,1,1,1]

        x = self.upsample(x)
        # print("After Expanding:"+str(x.shape))
        # print(x.shape)
        x = self.conv1(x)
        # print("After Conv1:" + str(x.shape))
        # print(x.shape)
        #使用裁剪操作将上一步生成的数据裁剪过后与现有生成数据拼接
        skip_con_x = self.crop(skip_con_x, x.shape)
        # print("skip_con_x.shape:"+str(skip_con_x.shape))
        # print("x.shape:" + str(x.shape))
        x = torch.cat([x, skip_con_x], axis=1)
        # print("After concact:"+x.shape)
        x = self.conv2(x)
        # print("X AFTER CONV2:"+str(x.shape))
        if self.use_bn and x.shape[3] >1 :
            x = self.instancenorm(x)
        if self.use_dropout:
            x = self.dropout(x)
        x = self.activation(x)
        x = self.conv3(x)
        if self.use_bn :
            x = self.instancenorm(x)
        if self.use_dropout:
            x = self.dropout(x)
        x = self.activation(x)
        return x
    
    def crop(self,image, new_shape):
        '''
        Function for cropping an image tensor: Given an image tensor and the new shape,
        crops to the center pixels (assumes that the input's size and the new size are
        even numbers).
        Parameters:
            image: image tensor of shape (batch size, channels, height, width)
            new_shape: a torch.Size object with the shape you want x to have
        '''
        middle_depth=image.shape[2] //2
        middle_height = image.shape[3] // 2
        middle_width = image.shape[4] // 2
        starting_depth=middle_depth-new_shape[2]//2
        final_depth=starting_depth+new_shape[2]
        starting_height = middle_height - new_shape[3] // 2
        final_height = starting_height + new_shape[3]
        starting_width = middle_width - new_shape[4] // 2
        final_width = starting_width + new_shape[4]
        cropped_image = image[:, :,starting_depth:final_depth, starting_height:final_height, starting_width:final_width]
        return cropped_image                    

class FeatureMapBlock(nn.Module):
    '''
    FeatureMapBlock Class
    The final layer of a U-Net -
    maps each pixel to a pixel with the correct number of output dimensions
    using a 1x1 convolution.
    Values:
        input_channels: the number of channels to expect from a given input
        output_channels: the number of channels to expect for a given output
    '''
    def __init__(self, input_channels, output_channels):
        super(FeatureMapBlock, self).__init__()
        # self.conv = nn.Conv2d(input_channels, output_channels, kernel_size=1)
        self.conv = nn.Conv3d(input_channels, output_channels, kernel_size=1)

    def forward(self, x):
        '''
        Function for completing a forward pass of FeatureMapBlock:
        Given an image tensor, returns it mapped to the desired number of channels.
        Parameters:
            x: image tensor of shape (batch size, channels, height, width)
        '''
        x = self.conv(x)
        return x

class ResUNet_LRes(nn.Module):
    #Generator
    '''
    UNet Class
    A series of 4 contracting blocks followed by 4 expanding blocks to
    transform an input image into the corresponding paired image, with an upfeature
    layer at the start and a downfeature layer at the end.
    Values:
        input_channels: the number of channels to expect from a given input
        output_channels: the number of channels to expect for a given output
    '''
    def __init__(self, in_channel, out_channel, hidden_channels=32):
        super(ResUNet_LRes, self).__init__()
        input_channels = in_channel
        output_channels = out_channel
        self.upfeature = FeatureMapBlock(input_channels, hidden_channels)
        self.contract1 = ContractingBlock(hidden_channels, use_dropout=True)
        self.contract2 = ContractingBlock(hidden_channels * 2, use_dropout=True)
        # self.contract3 = ContractingBlock(hidden_channels * 4, use_dropout=True,s1=(2,2,3))
        self.contract3 = ContractingBlock(hidden_channels * 4, use_dropout=True)
        # self.contract4 = ContractingBlock(hidden_channels * 8,k1=(2,2,1),s1=(2,2,1))
        self.contract4 = ContractingBlock(hidden_channels * 8,k1=(1,2,1),s1=(1,2,1))
        # self.contract5 = ContractingBlock(hidden_channels * 16,k1=(1,1,1),s1=(1,1,1))
        self.contract5 = ContractingBlock(hidden_channels * 16, k1=(1,1,1),s1=(1,1,1))
        self.contract6 = ContractingBlock(hidden_channels * 32,k1=(1,1,1),s1=(1,1,1))
        self.expand0 = ExpandingBlock(hidden_channels * 64,s1=1)
        self.expand1 = ExpandingBlock(hidden_channels * 32,s1=1)
        # self.expand1 = ExpandingBlock(hidden_channels * 32, s1=(1,2,1))
        # self.expand2 = ExpandingBlock(hidden_channels * 16,s1=(2,2,1))
        self.expand2 = ExpandingBlock(hidden_channels * 16,s1=(1,2,1))
        # self.expand3 = ExpandingBlock(hidden_channels * 8,s1=(2,2,3))
        self.expand3 = ExpandingBlock(hidden_channels * 8)
        self.expand4 = ExpandingBlock(hidden_channels * 4)
        self.expand5 = ExpandingBlock(hidden_channels * 2)
        self.downfeature = FeatureMapBlock(hidden_channels, output_channels)
        # self.deconv=nn.ConvTranspose3d(1,1,kernel_size=(9,9,6),stride=1,padding=0,dilation=(2,6,4))
        self.sigmoid = torch.nn.Sigmoid()

    def forward(self, x):
        '''
        Function for completing a forward pass of UNet:
        Given an image tensor, passes it through U-Net and returns the output.
        Parameters:
            x: image tensor of shape (batch size, channels, height, width)
        '''
        x0 = self.upfeature(x)
        x1 = self.contract1(x0)
        x2 = self.contract2(x1)
        x3 = self.contract3(x2)
        # print("X3.shape:"+str(x3.shape))
        x4 = self.contract4(x3)
        # print("X4.shape:" + str(x4.shape))
        x5 = self.contract5(x4)
        # print("X5.shape:" + str(x5.shape))
        x6 = self.contract6(x5)
        # print("X6.shape:" + str(x6.shape))

        # print("X6.shape:"+str(x6.shape))
        # print(x5.shape)
        # x6=x6.squeeze(0)
        x7 = self.expand0(x6, x5)
        # print("X7.shape:" + str(x7.shape))
        x8 = self.expand1(x7, x4)
        # print("X8.shape:" + str(x8.shape))
        x9 = self.expand2(x8, x3)
        # print("X9.shape:" + str(x9.shape))
        x10 = self.expand3(x9, x2)
        # print("X10.shape:" + str(x10.shape))
        x11 = self.expand4(x10, x1)
        # print("X11.shape:" + str(x11.shape))
        x12 = self.expand5(x11, x0)
        # print("X12.shape:" + str(x12.shape))
        # print("X12 shape"+str(x12.shape))
        xn = self.downfeature(x12)
        # print("Xn shape" + str(xn.shape))
        # xn=self.deconv(xn)

        return self.sigmoid(xn)

# UNQ_C1 (UNIQUE CELL IDENTIFIER, DO NOT EDIT)
# GRADED CLASS: Discriminator
class Discriminator(nn.Module):
    '''
    Discriminator Class
    Structured like the contracting path of the U-Net, the discriminator will
    output a matrix of values classifying corresponding portions of the image as real or fake.
    Parameters:
        input_channels: the number of image input channels
        hidden_channels: the initial number of discriminator convolutional filters
    '''
    def __init__(self, input_channels, hidden_channels=8):
        super(Discriminator, self).__init__()
        self.upfeature = FeatureMapBlock(input_channels, hidden_channels)
        self.contract1 = ContractingBlock(hidden_channels, use_bn=False)
        self.contract2 = ContractingBlock(hidden_channels * 2)
        self.contract3 = ContractingBlock(hidden_channels * 4)
        self.contract4 = ContractingBlock(hidden_channels * 8)
        #### START CODE HERE ####
        # self.final = nn.Conv2d(hidden_channels * 16, None, kernel_size=None)
        self.final = nn.Conv3d(hidden_channels * 16, 1, kernel_size=1)
        #### END CODE HERE ####

    def forward(self, x, y):
        # print(x.shape)
        # print(y.shape)
        x = torch.cat([x, y], axis=1)
        x0 = self.upfeature(x)
        x1 = self.contract1(x0)
        x2 = self.contract2(x1)
        x3 = self.contract3(x2)
        x4 = self.contract4(x3)
        xn = self.final(x4)
        return xn